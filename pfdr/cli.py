from __future__ import annotations

import json
import sys
from typing import Optional

import typer

from . import __version__
from .config import Settings
from .models import Paper
from .services import (
    ConfigurationService,
    FetchOptions,
    IngestionService,
    QueryOptions,
    QueryService,
    RemovalOptions,
    SourceSelectionError,
    TaskService,
)
from .tasks import TaskManager
from .webui import WebUI

app = typer.Typer(
    name="pfdr",
    help="A tool for fetching academic papers from DBLP and querying them using semantic search.",
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

    settings = Settings()
    task_manager = TaskManager(settings=settings)
    service = IngestionService(settings, task_manager=task_manager)
    options = FetchOptions(
        source_url=source_url,
        sources_file=sources_file,
        target_name=target_name,
        all_targets=all_targets,
        page_size=page_size,
        max_entries=max_entries,
        resume_task=resume_task,
    )

    try:
        sources = service.resolve_sources(options)
    except (SourceSelectionError, OSError) as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from exc

    if options.target_name:
        print(f"Using configured target: {options.target_name}")
    elif options.all_targets:
        print(f"Using {len(sources)} enabled targets from configuration.")
    elif options.sources_file:
        print(f"Loaded {len(sources)} sources from file '{options.sources_file}'.")

    try:
        summary = service.run_fetch(options, sources=sources)
    except SourceSelectionError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from exc

    print(f"Starting fetch task: {summary.task.task_id}")
    print("\nFetch completed!")
    print(f"Total papers in database: {summary.final_paper_count}")
    print(f"New papers added: {summary.new_papers}")
    print(f"Sources processed: {len(summary.sources)}")


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

    service = QueryService(Settings())
    papers = service.list_papers()
    if not papers:
        print("No papers stored. Run the fetch command first.")
        raise typer.Exit(1)

    print(f"Querying {len(papers)} papers with prompt: '{prompt}'")

    ranked = service.rank(QueryOptions(prompt=prompt, top_k=top_k), papers=papers)

    if service.client.backend and getattr(service.client.backend, "is_configured", False):
        print("Using DeepSeek API for semantic ranking...")
    else:
        print("DeepSeek API not configured, using keyword-based ranking...")

    print(f"Found {len(ranked)} relevant papers")

    if json_output:
        print(json.dumps([item.to_dict() for item in ranked], ensure_ascii=False, indent=2))
    else:
        _print_ranked_table(ranked)


@app.command()
def tasks():
    """List known tasks and their status."""

    task_service = TaskService(Settings())
    tasks = list(task_service.list_tasks())

    if not tasks:
        print("No tasks recorded yet.")
        return

    print("Task Status:\n")
    for task in tasks:
        print(
            f"  {task.task_id[:8]}... {task.status:<12} {task.task_type:<12} {task.progress}"
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

    settings = Settings()
    service = IngestionService(settings)
    options = RemovalOptions(pattern=pattern, source_url=source_url, target_name=target_name)

    try:
        plan = service.plan_removal(options)
    except SourceSelectionError as exc:
        print(f"Error: {exc}")
        raise typer.Exit(1) from exc

    if plan.is_empty():
        print("No matching sources found.")
        return

    print(f"Found {len(plan.sources)} sources to remove:")
    for source in plan.sources:
        print(f"  {source}")

    print(f"Matched {plan.state_count} ingestion states.")

    print(
        f"\nWould delete {plan.deleted_count} papers from {len(plan.sources)} sources."
    )

    if dry_run:
        print("Dry run mode - no changes made.")
        return

    if not force and not typer.confirm(
        "Are you sure you want to delete these sources and papers?"
    ):
        print("Operation cancelled.")
        return

    deleted_states, deleted_papers = service.apply_removal(plan)

    if target_name:
        config_service = ConfigurationService(settings)
        if config_service.remove_target(target_name):
            print(f"Removed target '{target_name}' from configuration.")

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

    service = ConfigurationService(Settings())

    if init:
        try:
            path = service.create_default()
            print(f"Created default configuration at {path}")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"Failed to create default config: {exc}")
            raise typer.Exit(1) from exc
        return

    if show:
        summary = service.summary()
        print(f"Configuration file: {summary.config_file}")
        print(f"LLM Provider: {summary.llm_provider}")
        print(
            "LLM API Key: "
            f"{'*' * 20 if summary.llm_api_key else 'Not set'}"
        )
        print(f"LLM API Base: {summary.llm_api_base}")
        print(f"LLM Model: {summary.llm_model}")
        print(f"Data Directory: {summary.data_dir}")
        print(f"Ingestion Targets: {summary.ingestion_targets}")
        return

    if add_target:
        try:
            name, url = _parse_target_spec(add_target)
            service.add_target(name, url)
            print(f"Added target: {name}")
        except Exception as exc:  # pylint: disable=broad-except
            print(f"Failed to add target: {exc}")
            raise typer.Exit(1) from exc
        return

    if list_targets:
        targets = list(service.list_targets())
        if not targets:
            print("No ingestion targets configured.")
            return
        print("Configured Ingestion Targets:\n")
        for target in targets:
            status = "enabled" if target.enabled else "disabled"
            print(f"  {target.name}")
            print(f"    URL: {target.url}")
            print(f"    Status: {status}\n")
        return

    print("Use --help to see available config options.")


@app.command()
def sync():
    """Sync current local ingestion states back to YAML configuration."""

    service = IngestionService(Settings())
    synced_count, targets = service.sync_to_config()

    if synced_count == 0:
        print("No ingestion states found to sync.")
        return

    print(f"Configuration synced to {service.settings.config_file}")
    print(f"Synced {synced_count} targets:")
    for item in targets:
        print(f"  {item}")


@app.command()
def webui(
    host: Optional[str] = typer.Option(
        None, "--host", help="Host to bind the web server to (overrides config)"
    ),
    port: Optional[int] = typer.Option(
        None, "--port", help="Port to bind the web server to (overrides config)"
    ),
    reload: Optional[bool] = typer.Option(
        None, "--reload", help="Enable auto-reload for development (overrides config)"
    ),
):
    """Start the web UI server."""

    settings = Settings()
    final_host = host if host is not None else settings.webui_host
    final_port = port if port is not None else settings.webui_port
    final_reload = reload if reload is not None else settings.webui_reload

    print(f"Starting pfdr Web UI on http://{final_host}:{final_port}")
    print("Press Ctrl+C to stop the server")

    webui = WebUI(settings)
    webui.run(host=final_host, port=final_port, reload=final_reload)


@app.command(name="list")
def list_items(
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

    if sum([sources, papers, authors]) != 1:
        print("Error: Must specify exactly one of --sources, --papers, or --authors")
        raise typer.Exit(1)

    service = QueryService(Settings())

    if sources:
        mapping = service.papers_by_sources(pattern)
        if not mapping:
            print("No sources found.")
            return
        items = list(mapping.items())[:limit]
        if json_output:
            payload = {
                source: [paper.to_dict() for paper in papers_for_source]
                for source, papers_for_source in items
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        print(f"Sources (showing {len(items)}):\n")
        for source, papers_for_source in items:
            print(f"  {source or 'Unknown source'}")
            print(f"    Papers: {len(papers_for_source)}\n")
        return

    if papers:
        paper_list = service.list_papers()
        if pattern:
            paper_list = [
                paper
                for paper in paper_list
                if pattern.lower() in (paper.source or "").lower()
                or pattern.lower() in paper.title.lower()
            ]
        paper_list = paper_list[:limit]
        if not paper_list:
            print("No papers found.")
            return
        if json_output:
            print(json.dumps([paper.to_dict() for paper in paper_list], ensure_ascii=False, indent=2))
            return
        print(f"Papers (showing {len(paper_list)}):\n")
        for paper in paper_list:
            authors_str = ", ".join(paper.authors[:3])
            if len(paper.authors) > 3:
                authors_str += f" (+{len(paper.authors) - 3} more)"
            print(f"  {paper.title}")
            print(f"    Authors: {authors_str}")
            print(f"    Venue: {paper.venue or 'N/A'}")
            print(f"    Year: {paper.year or 'N/A'}")
            print(f"    DOI: {paper.doi or 'N/A'}\n")
        return

    if authors:
        author_counts = service.authors_by_frequency(pattern)
        author_counts = author_counts[:limit]
        if not author_counts:
            print("No authors found.")
            return
        if json_output:
            payload = [
                {"author": author, "paper_count": count}
                for author, count in author_counts
            ]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        print(f"Authors (showing {len(author_counts)}):\n")
        for author, count in author_counts:
            print(f"  {author:<40} {count} papers")


def _parse_target_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ValueError("Target format should be 'name:url'")
    name, url = spec.split(":", 1)
    if not name or not url:
        raise ValueError("Target format should be 'name:url'")
    return name, url


def _print_ranked_table(ranked) -> None:
    print("Query Results:\n")
    for idx, item in enumerate(ranked, start=1):
        paper: Paper = item.paper
        authors = ", ".join(paper.authors[:3])
        if len(paper.authors) > 3:
            authors += f" (+{len(paper.authors) - 3} more)"
        print(f"  {idx}. {paper.title}")
        print(f"     Authors: {authors}")
        print(f"     Venue: {paper.venue or 'N/A'}")
        print(f"     Score: {item.score:.3f}")
        if getattr(item, "reason", None):
            print(f"     Reason: {item.reason}")
        print()


def main(argv: list[str] | None = None):
    if argv is None:
        argv = sys.argv[1:]

    if "--version" in argv:
        print(f"pfdr version {__version__}, wheatfox <wheatfox17@icloud.com>")
        return

    try:
        app(argv)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"An unexpected error occurred: {exc}")
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    main()
