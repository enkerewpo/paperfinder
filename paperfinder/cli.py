"""Command-line interface for paperfinder."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable
from pathlib import Path

from .config import Settings
from .dblp import DblpIngestionTaskRunner
from .deepseek import DeepSeekClient
from .models import Paper
from .state import IngestionStateStore
from .storage import PaperStore
from .tasks import TaskManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperfinder", description="DBLP ingestion and DeepSeek-powered querying.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch papers from a DBLP API endpoint")
    sources_group = fetch_parser.add_mutually_exclusive_group(required=True)
    sources_group.add_argument(
        "--source-url",
        help="Single DBLP search API URL, e.g. https://dblp.org/search/publ/api?q=stream:conf/nips:2023",
    )
    sources_group.add_argument(
        "--sources-file",
        help="Text file containing DBLP API URLs (one per line, # for comments)",
    )
    fetch_parser.add_argument("--page-size", type=int, default=200, help="Number of entries to fetch per batch")
    fetch_parser.add_argument("--max-entries", type=int, default=None, help="Optional maximum number of entries to ingest")
    fetch_parser.add_argument("--resume-task", help="Existing task identifier to resume")

    query_parser = subparsers.add_parser("query", help="Rank stored papers against a natural language query")
    query_parser.add_argument("--prompt", required=True, help="Search intent expressed in natural language")
    query_parser.add_argument("--top-k", type=int, default=10, help="Number of results to return")
    query_parser.add_argument("--json", dest="json_output", action="store_true", help="Print raw JSON instead of a table")

    subparsers.add_parser("tasks", help="List known tasks and their status")

    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up ingestion states and papers")
    cleanup_parser.add_argument("--pattern", help="Pattern to match source URLs (case-insensitive)")
    cleanup_parser.add_argument("--source-url", help="Exact source URL to remove")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    cleanup_parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    list_parser = subparsers.add_parser("list", help="List various data")
    list_group = list_parser.add_mutually_exclusive_group(required=True)
    list_group.add_argument("--sources", action="store_true", help="List ingestion sources")
    list_group.add_argument("--papers", action="store_true", help="List papers")
    list_group.add_argument("--authors", action="store_true", help="List authors")
    list_parser.add_argument("--limit", type=int, default=20, help="Limit number of results")
    list_parser.add_argument("--pattern", help="Filter by pattern (case-insensitive)")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


def handle_fetch(args: argparse.Namespace, settings: Settings) -> None:
    manager = TaskManager(settings=settings)
    runner = DblpIngestionTaskRunner(settings=settings, page_size=args.page_size)

    if args.sources_file:
        try:
            sources = _load_sources_file(args.sources_file)
        except OSError as exc:
            print(f"Unable to read sources file: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        sources = [args.source_url]

    if not sources:
        print("No valid DBLP sources provided.", file=sys.stderr)
        sys.exit(1)

    if args.resume_task:
        task = manager.resume(args.resume_task)
        if task is None:
            print(f"Task {args.resume_task} not found.", file=sys.stderr)
            sys.exit(1)
    else:
        task = manager.enqueue(
            "dblp_ingest",
            payload={
                "sources": sources,
                "max_entries": args.max_entries,
            },
        )

    for pending in manager.drain():
        if pending.task_id != task.task_id:
            continue
        runner.run(manager, pending)
        break


def handle_query(args: argparse.Namespace, settings: Settings) -> None:
    store = PaperStore(settings)
    papers = store.list()
    if not papers:
        print("No papers stored. Run the fetch command first.", file=sys.stderr)
        sys.exit(1)

    client = DeepSeekClient(settings)
    ranked = client.rank_papers(args.prompt, papers, top_k=args.top_k)
    if args.json_output:
        print(json.dumps([item.to_dict() for item in ranked], ensure_ascii=False, indent=2))
    else:
        _print_ranked_table(ranked)


def handle_tasks(settings: Settings) -> None:
    manager = TaskManager(settings=settings)
    tasks = manager.store.list()
    if not tasks:
        print("No tasks recorded yet.")
        return
    for task in tasks:
        print(f"{task.task_id} [{task.status.value}] {task.task_type} progress={task.progress}/{task.total or '?'}")


def handle_cleanup(args: argparse.Namespace, settings: Settings) -> None:
    state_store = IngestionStateStore(settings)
    paper_store = PaperStore(settings)
    
    if not args.pattern and not args.source_url:
        print("Error: Must specify either --pattern or --source-url", file=sys.stderr)
        sys.exit(1)
    
    if args.pattern and args.source_url:
        print("Error: Cannot specify both --pattern and --source-url", file=sys.stderr)
        sys.exit(1)
    
    # Determine sources to delete
    sources_to_delete = []
    
    if args.pattern:
        states = state_store.list()
        matching_sources = [state.source_url for state in states if args.pattern.lower() in state.source_url.lower()]
        sources_to_delete = matching_sources
        print(f"Found {len(matching_sources)} sources matching pattern '{args.pattern}':")
        for source in matching_sources:
            print(f"  {source}")
    
    elif args.source_url:
        states = state_store.list()
        if args.source_url in [state.source_url for state in states]:
            sources_to_delete = [args.source_url]
            print(f"Found source: {args.source_url}")
        else:
            print(f"Source URL '{args.source_url}' not found in ingestion states.")
            return
    
    if not sources_to_delete:
        print("No matching sources found.")
        return
    
    # Count papers that would be deleted
    papers = paper_store.list()
    papers_to_delete = [paper for paper in papers if paper.source in sources_to_delete]
    
    print(f"\nWould delete {len(papers_to_delete)} papers from {len(sources_to_delete)} sources.")
    
    if args.dry_run:
        print("Dry run mode - no changes made.")
        return
    
    # Confirm deletion unless forced
    if not args.force:
        response = input("Are you sure you want to delete these sources and papers? (y/N): ")
        if response.lower() != 'y':
            print("Operation cancelled.")
            return
    
    # Delete ingestion states
    deleted_states = 0
    if args.pattern:
        deleted_sources = state_store.delete_by_pattern(args.pattern)
        deleted_states = len(deleted_sources)
    else:
        if state_store.delete_by_source(args.source_url):
            deleted_states = 1
    
    # Delete papers
    deleted_papers = paper_store.delete_by_sources(sources_to_delete)
    
    print(f"Successfully deleted {deleted_states} ingestion states and {deleted_papers} papers.")


def handle_list(args: argparse.Namespace, settings: Settings) -> None:
    state_store = IngestionStateStore(settings)
    paper_store = PaperStore(settings)
    
    if args.sources:
        states = state_store.list()
        if args.pattern:
            states = [state for state in states if args.pattern.lower() in state.source_url.lower()]
        
        states = states[:args.limit]
        
        if args.json:
            output = []
            for state in states:
                output.append({
                    "source_url": state.source_url,
                    "offset": state.offset,
                    "total_collected": state.total_collected,
                    "total_available": state.total_available,
                    "updated_at": state.updated_at
                })
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not states:
                print("No ingestion sources found.")
                return
            
            print(f"Ingestion sources (showing {len(states)}):")
            for state in states:
                print(f"  {state.source_url}")
                print(f"    Offset: {state.offset}, Collected: {state.total_collected}, Available: {state.total_available}")
                print(f"    Updated: {state.updated_at}")
    
    elif args.papers:
        papers = paper_store.list()
        if args.pattern:
            papers = [paper for paper in papers if args.pattern.lower() in paper.title.lower()]
        
        papers = papers[:args.limit]
        
        if args.json:
            output = [paper.to_dict() for paper in papers]
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not papers:
                print("No papers found.")
                return
            
            print(f"Papers (showing {len(papers)}):")
            for paper in papers:
                print(f"  {paper.title}")
                if paper.authors:
                    authors = ", ".join(paper.authors[:3])
                    if len(paper.authors) > 3:
                        authors += f" (+{len(paper.authors) - 3} more)"
                    print(f"    Authors: {authors}")
                if paper.venue:
                    print(f"    Venue: {paper.venue} ({paper.year or 'n/a'})")
                if paper.doi:
                    print(f"    DOI: {paper.doi}")
                print()
    
    elif args.authors:
        papers = paper_store.list()
        author_counts = {}
        
        for paper in papers:
            for author in paper.authors:
                if args.pattern and args.pattern.lower() not in author.lower():
                    continue
                author_counts[author] = author_counts.get(author, 0) + 1
        
        # Sort by paper count (descending)
        sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
        sorted_authors = sorted_authors[:args.limit]
        
        if args.json:
            output = [{"author": author, "paper_count": count} for author, count in sorted_authors]
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not sorted_authors:
                print("No authors found.")
                return
            
            print(f"Authors (showing {len(sorted_authors)}):")
            for author, count in sorted_authors:
                print(f"  {author} ({count} papers)")


def _print_ranked_table(ranked: Iterable) -> None:
    for idx, item in enumerate(ranked, start=1):
        paper: Paper = item.paper
        print(f"[{idx}] {paper.title}")
        authors = ", ".join(paper.authors[:5])
        if len(paper.authors) > 5:
            authors += ", ..."
        if authors:
            print(f"    Authors: {authors}")
        if paper.venue:
            print(f"    Venue: {paper.venue} ({paper.year or 'n/a'})")
        if paper.doi:
            print(f"    DOI: {paper.doi}")
        print(f"    Score: {item.score:.3f}")
        if item.reason:
            print(f"    Reason: {item.reason}")
        print()


def _load_sources_file(path: str) -> list[str]:
    sources: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate not in sources:
            sources.append(candidate)
    return sources


def main(argv: list[str] | None = None) -> None:
    settings = Settings()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "fetch":
        handle_fetch(args, settings)
    elif args.command == "query":
        handle_query(args, settings)
    elif args.command == "tasks":
        handle_tasks(settings)
    elif args.command == "cleanup":
        handle_cleanup(args, settings)
    elif args.command == "list":
        handle_list(args, settings)
    else:
        parser.print_help()


if __name__ == "__main__":  # pragma: no cover
    main()
