from __future__ import annotations

import json
import sys
from typing import Optional
from pathlib import Path

import typer

from . import __version__
from .config import Settings, IngestionTarget
from .dblp import DblpIngestionTaskRunner
from .deepseek import DeepSeekClient
from .models import Paper
from .state import IngestionStateStore
from .storage import PaperStore
from .tasks import TaskManager

app = typer.Typer(
    name="pfdr",
    help="A powerful tool for fetching academic papers from DBLP and querying them using AI-powered semantic search.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
    add_completion=False,
)


@app.command()
def fetch(
    source_url: Optional[str] = typer.Option(
        None, "--source-url", help="Single DBLP search API URL to fetch papers from"
    ),
    sources_file: Optional[str] = typer.Option(
        None,
        "--sources-file",
        help="Path to a text file containing DBLP API URLs (one per line)",
    ),
    target_name: Optional[str] = typer.Option(
        None, "--target", help="Name of a configured ingestion target from config.yaml"
    ),
    all_targets: bool = typer.Option(
        False, "--all-targets", help="Fetch from all enabled targets in config.yaml"
    ),
    page_size: int = typer.Option(
        200, "--page-size", help="Number of papers to fetch per API request batch"
    ),
    max_entries: Optional[int] = typer.Option(
        None, "--max-entries", help="Maximum number of papers to fetch in total"
    ),
    resume_task: Optional[str] = typer.Option(
        None,
        "--resume-task",
        help="Resume a previously interrupted fetch task using its task ID",
    ),
):
    """Fetch academic papers from DBLP API endpoints."""
    # Count how many source options are provided
    source_options = sum(
        [bool(source_url), bool(sources_file), bool(target_name), all_targets]
    )

    if source_options == 0:
        print(
            "Error: Must specify one of --source-url, --sources-file, --target, or --all-targets"
        )
        raise typer.Exit(1)

    if source_options > 1:
        print("Error: Can only specify one source option at a time")
        raise typer.Exit(1)

    settings = Settings()
    manager = TaskManager(settings=settings)
    runner = DblpIngestionTaskRunner(settings=settings, page_size=page_size)

    sources = []

    if source_url:
        sources = [source_url]
    elif sources_file:
        try:
            sources = _load_sources_file(sources_file)
        except OSError as exc:
            print(f"Unable to read sources file: {exc}")
            raise typer.Exit(1)
    elif target_name:
        # Find the target by name
        target = None
        for t in settings.ingestion_targets:
            if t.name == target_name:
                target = t
                break

        if not target:
            print(f"Target '{target_name}' not found in configuration.")
            print(
                f"Available targets: {', '.join([t.name for t in settings.ingestion_targets])}"
            )
            raise typer.Exit(1)

        if not target.enabled:
            print(f"Target '{target_name}' is disabled.")
            raise typer.Exit(1)

        sources = [target.url]
        print(f"Using configured target: {target.name}")
    elif all_targets:
        enabled_targets = settings.get_enabled_targets()
        if not enabled_targets:
            print("No enabled targets found in configuration.")
            raise typer.Exit(1)

        sources = [target.url for target in enabled_targets]
        print(f"Using {len(enabled_targets)} enabled targets from configuration.")

    if not sources:
        print("No valid DBLP sources provided.")
        raise typer.Exit(1)

    if resume_task:
        task = manager.resume(resume_task)
        if task is None:
            print(f"Task {resume_task} not found.")
            raise typer.Exit(1)
    else:
        task = manager.enqueue(
            "dblp_ingest",
            payload={
                "sources": sources,
                "max_entries": max_entries,
            },
        )

    print(f"Starting fetch task: {task.task_id}")

    # Track initial paper count
    initial_paper_count = len(PaperStore(settings).list())

    for pending in manager.drain():
        if pending.task_id != task.task_id:
            continue
        runner.run(manager, pending)
        break

    # Show final statistics
    final_paper_count = len(PaperStore(settings).list())
    new_papers = final_paper_count - initial_paper_count

    print(f"\nFetch completed!")
    print(f"Total papers in database: {final_paper_count}")
    print(f"New papers added: {new_papers}")
    print(f"Sources processed: {len(sources)}")


@app.command()
def query(
    prompt: str = typer.Argument(
        ..., help="Search intent expressed in natural language"
    ),
    top_k: int = typer.Option(10, "--top-k", help="Number of results to return"),
    json_output: bool = typer.Option(
        False, "--json", help="Print raw JSON instead of a table"
    ),
):
    """Rank stored papers against a natural language query using AI."""
    settings = Settings()
    store = PaperStore(settings)
    papers = store.list()

    if not papers:
        print("No papers stored. Run the fetch command first.")
        raise typer.Exit(1)

    print(f"Querying {len(papers)} papers with prompt: '{prompt}'")

    client = DeepSeekClient(settings)
    
    if client.is_configured:
        print("Using DeepSeek API for semantic ranking...")
    else:
        print("DeepSeek API not configured, using keyword-based ranking...")
    
    ranked = client.rank_papers(prompt, papers, top_k=top_k)
    
    print(f"Found {len(ranked)} relevant papers")

    if json_output:
        print(
            json.dumps(
                [item.to_dict() for item in ranked], ensure_ascii=False, indent=2
            )
        )
    else:
        _print_ranked_table(ranked)


@app.command()
def tasks(
):
    """List known tasks and their status."""
    settings = Settings()
    manager = TaskManager(settings=settings)
    tasks = manager.store.list()

    if not tasks:
        print("No tasks recorded yet.")
        return

    print("Task Status:")
    print()
    for task in tasks:
        progress = f"{task.progress}/{task.total or '?'}"
        status_color = (
            "green"
            if task.status.value == "completed"
            else "red"
            if task.status.value == "failed"
            else "yellow"
        )
        print(
            f"  {task.task_id[:8]}... {task.status.value:<12} {task.task_type:<12} {progress}"
        )


@app.command()
def remove(
    pattern: Optional[str] = typer.Option(
        None, "--pattern", help="Pattern to match source URLs (case-insensitive)"
    ),
    source_url: Optional[str] = typer.Option(
        None, "--source-url", help="Exact source URL to remove"
    ),
    target_name: Optional[str] = typer.Option(
        None, "--target", help="Name of a configured ingestion target to remove"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be deleted without actually deleting"
    ),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt"),
):
    """Remove ingestion states and papers."""
    # Count how many removal options are provided
    removal_options = sum([bool(pattern), bool(source_url), bool(target_name)])

    if removal_options == 0:
        print("Error: Must specify one of --pattern, --source-url, or --target")
        raise typer.Exit(1)

    if removal_options > 1:
        print("Error: Can only specify one removal option at a time")
        raise typer.Exit(1)

    settings = Settings()
    state_store = IngestionStateStore(settings)
    paper_store = PaperStore(settings)

    # Determine sources to delete
    sources_to_delete = []

    if pattern:
        states = state_store.list()
        matching_sources = [
            state.source_url
            for state in states
            if pattern.lower() in state.source_url.lower()
        ]
        sources_to_delete = matching_sources
        print(f"Found {len(matching_sources)} sources matching pattern '{pattern}':")
        for source in matching_sources:
            print(f"  {source}")

    elif source_url:
        states = state_store.list()
        if source_url in [state.source_url for state in states]:
            sources_to_delete = [source_url]
            print(f"Found source: {source_url}")
        else:
            print(f"Source URL '{source_url}' not found in ingestion states.")
            return

    elif target_name:
        # Find the target by name
        target = None
        for t in settings.ingestion_targets:
            if t.name == target_name:
                target = t
                break

        if not target:
            print(f"Target '{target_name}' not found in configuration.")
            print(
                f"Available targets: {', '.join([t.name for t in settings.ingestion_targets])}"
            )
            raise typer.Exit(1)

        sources_to_delete = [target.url]
        print(f"Removing target: {target.name}")

        # Also remove from configuration
        if settings.remove_ingestion_target(target_name):
            settings.save_to_yaml()  # Automatically save changes
            print(f"Removed target '{target_name}' from configuration.")
        else:
            print(f"Target '{target_name}' not found in configuration.")

    if not sources_to_delete:
        print("No matching sources found.")
        return

    # Count papers that would be deleted
    papers = paper_store.list()
    papers_to_delete = [paper for paper in papers if paper.source in sources_to_delete]

    print(
        f"\nWould delete {len(papers_to_delete)} papers from {len(sources_to_delete)} sources."
    )

    if dry_run:
        print("Dry run mode - no changes made.")
        return

    # Confirm deletion unless forced
    if not force:
        if not typer.confirm(
            "Are you sure you want to delete these sources and papers?"
        ):
            print("Operation cancelled.")
            return

    # Delete ingestion states
    deleted_states = 0
    if pattern:
        deleted_sources = state_store.delete_by_pattern(pattern)
        deleted_states = len(deleted_sources)
    else:
        if state_store.delete_by_source(source_url):
            deleted_states = 1

    # Delete papers
    deleted_papers = paper_store.delete_by_sources(sources_to_delete)

    print(
        f"Successfully deleted {deleted_states} ingestion states and {deleted_papers} papers."
    )


@app.command()
def config(
    init: bool = typer.Option(
        False, "--init", help="Initialize a default config.yaml file"
    ),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
    add_target: Optional[str] = typer.Option(
        None, "--add-target", help="Add a new ingestion target (format: name:url)"
    ),
    list_targets: bool = typer.Option(
        False, "--list-targets", help="List all configured ingestion targets"
    ),
):
    """Manage configuration settings."""
    settings = Settings()

    if init:
        try:
            settings.create_default_config()
            print(f"Created default configuration at {settings.config_file}")
        except Exception as e:
            print(f"Failed to create default config: {e}")
            raise typer.Exit(1)

    elif show:
        print(f"Configuration file: {settings.config_file}")
        print(
            f"DeepSeek API Key: {'*' * 20 if settings.deepseek_api_key else 'Not set'}"
        )
        print(f"DeepSeek API Base: {settings.deepseek_api_base}")
        print(f"DeepSeek Model: {settings.deepseek_model}")
        print(f"Data Directory: {settings.data_dir}")
        print(f"Ingestion Targets: {len(settings.ingestion_targets)}")

    elif add_target:
        try:
            # Parse format: name:url
            # Handle URLs with :// by finding the first colon
            if "://" in add_target:
                # Split by first colon only
                parts = add_target.split(":", 1)
                if len(parts) != 2:
                    print("Error: Target format should be 'name:url'")
                    raise typer.Exit(1)
                name, url = parts[0], parts[1]
            else:
                # No :// in the string, use simple split
                parts = add_target.split(":", 1)
                if len(parts) != 2:
                    print("Error: Target format should be 'name:url'")
                    raise typer.Exit(1)
                name, url = parts[0], parts[1]

            settings.add_ingestion_target(name, url)
            settings.save_to_yaml()  # Automatically save changes
            print(f"Added target: {name}")
        except Exception as e:
            print(f"Failed to add target: {e}")
            raise typer.Exit(1)

    elif list_targets:
        if not settings.ingestion_targets:
            print("No ingestion targets configured.")
            return

        print("Configured Ingestion Targets:")
        print()
        for target in settings.ingestion_targets:
            status = "enabled" if target.enabled else "disabled"
            print(f"  {target.name}")
            print(f"    URL: {target.url}")
            print(f"    Status: {status}")
            print()

    else:
        print("Use --help to see available config options.")


@app.command()
def sync():
    """Sync current local ingestion states back to YAML configuration."""
    settings = Settings()
    state_store = IngestionStateStore(settings)

    # Get current ingestion states from local storage
    current_states = state_store.list()

    if not current_states:
        print("[yellow]No ingestion states found to sync.")
        return

    print(f"Found {len(current_states)} ingestion states to sync:")

    # Create/update ingestion targets based on current states
    synced_targets = []
    for state in current_states:
        # Extract a meaningful name from the URL
        name = _extract_target_name_from_url(state.source_url)

        # Create or update target
        target = None
        for existing_target in settings.ingestion_targets:
            if existing_target.url == state.source_url:
                target = existing_target
                break

        if not target:
            # Create new target
            target = IngestionTarget(name=name, url=state.source_url, enabled=True)
            settings.ingestion_targets.append(target)
            synced_targets.append(f"[green]Added: {name}")
        else:
            # Update existing target
            synced_targets.append(f"[blue]Updated: {name}")

    # Save updated configuration
    try:
        settings.save_to_yaml()
        print(f"Configuration synced to {settings.config_file}")
        print(f"Synced {len(synced_targets)} targets:")
        for target_info in synced_targets:
            print(f"  {target_info}")
    except Exception as e:
        print(f"Failed to sync configuration: {e}")
        raise typer.Exit(1)


@app.command()
def list(
    sources: bool = typer.Option(False, "--sources", help="List ingestion sources"),
    papers: bool = typer.Option(False, "--papers", help="List papers"),
    authors: bool = typer.Option(False, "--authors", help="List authors"),
    limit: int = typer.Option(20, "--limit", help="Limit number of results"),
    pattern: Optional[str] = typer.Option(
        None, "--pattern", help="Filter by pattern (case-insensitive)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List ingestion sources, papers, or authors."""
    if not sources and not papers and not authors:
        print("Error: Must specify one of --sources, --papers, or --authors")
        raise typer.Exit(1)

    if sum([sources, papers, authors]) > 1:
        print("Error: Can only specify one of --sources, --papers, or --authors")
        raise typer.Exit(1)

    settings = Settings()
    state_store = IngestionStateStore(settings)
    paper_store = PaperStore(settings)

    if sources:
        states = state_store.list()
        if pattern:
            states = [
                state for state in states if pattern.lower() in state.source_url.lower()
            ]

        states = states[:limit]

        if json_output:
            output = []
            for state in states:
                output.append(
                    {
                        "source_url": state.source_url,
                        "offset": state.offset,
                        "total_collected": state.total_collected,
                        "total_available": state.total_available,
                        "updated_at": state.updated_at,
                    }
                )
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not states:
                print("No ingestion sources found.")
                return

            print(f"Ingestion Sources (showing {len(states)}):")
            print()
            for state in states:
                print(f"  {state.source_url}")
                print(f"    Offset: {state.offset}")
                print(f"    Collected: {state.total_collected}")
                print(f"    Available: {state.total_available}")
                print(f"    Updated: {state.updated_at}")
                print()

    elif papers:
        papers = paper_store.list()
        if pattern:
            papers = [
                paper for paper in papers if pattern.lower() in paper.title.lower()
            ]

        papers = papers[:limit]

        if json_output:
            output = [paper.to_dict() for paper in papers]
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not papers:
                print("No papers found.")
                return

            print(f"Papers (showing {len(papers)}):")
            print()
            for paper in papers:
                authors = ", ".join(paper.authors[:3])
                if len(paper.authors) > 3:
                    authors += f" (+{len(paper.authors) - 3} more)"

                print(f"  {paper.title}")
                print(f"    Authors: {authors}")
                print(f"    Venue: {paper.venue or 'N/A'}")
                print(f"    Year: {paper.year or 'N/A'}")
                print(f"    DOI: {paper.doi or 'N/A'}")
                print()

    elif authors:
        papers = paper_store.list()
        author_counts = {}

        for paper in papers:
            for author in paper.authors:
                if pattern and pattern.lower() not in author.lower():
                    continue
                author_counts[author] = author_counts.get(author, 0) + 1

        # Sort by paper count (descending)
        sorted_authors = sorted(author_counts.items(), key=lambda x: x[1], reverse=True)
        sorted_authors = sorted_authors[:limit]

        if json_output:
            output = [
                {"author": author, "paper_count": count}
                for author, count in sorted_authors
            ]
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not sorted_authors:
                print("No authors found.")
                return

            print(f"Authors (showing {len(sorted_authors)}):")
            print()
            for author, count in sorted_authors:
                print(f"  {author:<40} {count} papers")


def _print_ranked_table(ranked) -> None:
    """Print ranked papers in a cargo-style format."""
    print("Query Results:")
    print()
    for idx, item in enumerate(ranked, start=1):
        paper: Paper = item.paper
        authors = ", ".join(paper.authors[:3])
        if len(paper.authors) > 3:
            authors += f" (+{len(paper.authors) - 3} more)"

        print(f"  {idx}. {paper.title}")
        print(f"     Authors: {authors}")
        print(f"     Venue: {paper.venue or 'N/A'}")
        print(f"     Score: {item.score:.3f}")
        if item.reason:
            print(f"     Reason: {item.reason}")
        print()


def _extract_target_name_from_url(url: str) -> str:
    """Extract a meaningful name from a DBLP URL."""
    # Extract conference/journal name and year from DBLP URLs
    # Example: https://dblp.org/search/publ/api?q=stream:conf/sosp:2025
    # Should become: sosp-2025

    if "stream:conf/" in url:
        # Conference papers
        parts = url.split("stream:conf/")[1].split(":")
        if len(parts) >= 2:
            conf_name = parts[0]
            year = parts[1].split("&")[0]  # Remove any query parameters
            return f"{conf_name}-{year}"
    elif "stream:journals/" in url:
        # Journal papers
        parts = url.split("stream:journals/")[1].split(":")
        if len(parts) >= 2:
            journal_name = parts[0]
            year = parts[1].split("&")[0]
            return f"{journal_name}-{year}"

    # Fallback: use a hash of the URL
    import hashlib

    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"target-{url_hash}"


def _load_sources_file(path: str) -> list[str]:
    """Load DBLP source URLs from a text file."""
    sources: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate not in sources:
            sources.append(candidate)
    return sources


def main(argv: list[str] | None = None):
    """Main entry point for the CLI."""
    # Use sys.argv if argv is not provided
    if argv is None:
        argv = sys.argv[1:]  # Skip script name
    
    # Handle global --version option
    if "--version" in argv:
        print(f"pfdr version {__version__}, wheatfox <wheatfox17@icloud.com>")
        return
    
    try:
        app(argv)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
