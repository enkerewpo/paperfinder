"""Command-line interface for paperfinder."""

from __future__ import annotations

import json
import sys
from typing import Optional
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .config import Settings, IngestionTarget
from .dblp import DblpIngestionTaskRunner
from .deepseek import DeepSeekClient
from .models import Paper
from .state import IngestionStateStore
from .storage import PaperStore
from .tasks import TaskManager

app = typer.Typer(
    name="paperfinder",
    help="A powerful tool for fetching academic papers from DBLP and querying them using AI-powered semantic search.",
    no_args_is_help=True,
    rich_markup_mode="rich"
)
console = Console()


@app.command()
def fetch(
    source_url: Optional[str] = typer.Option(
        None, 
        "--source-url", 
        help="Single DBLP search API URL to fetch papers from"
    ),
    sources_file: Optional[str] = typer.Option(
        None,
        "--sources-file", 
        help="Path to a text file containing DBLP API URLs (one per line)"
    ),
    target_name: Optional[str] = typer.Option(
        None,
        "--target",
        help="Name of a configured ingestion target from config.yaml"
    ),
    all_targets: bool = typer.Option(
        False,
        "--all-targets",
        help="Fetch from all enabled targets in config.yaml"
    ),
    page_size: int = typer.Option(
        200, 
        "--page-size", 
        help="Number of papers to fetch per API request batch"
    ),
    max_entries: Optional[int] = typer.Option(
        None, 
        "--max-entries", 
        help="Maximum number of papers to fetch in total"
    ),
    resume_task: Optional[str] = typer.Option(
        None, 
        "--resume-task", 
        help="Resume a previously interrupted fetch task using its task ID"
    )
):
    """Fetch academic papers from DBLP API endpoints."""
    # Count how many source options are provided
    source_options = sum([bool(source_url), bool(sources_file), bool(target_name), all_targets])
    
    if source_options == 0:
        console.print("[red]Error:[/red] Must specify one of --source-url, --sources-file, --target, or --all-targets")
        raise typer.Exit(1)
    
    if source_options > 1:
        console.print("[red]Error:[/red] Can only specify one source option at a time")
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
            console.print(f"[red]Unable to read sources file:[/red] {exc}")
            raise typer.Exit(1)
    elif target_name:
        # Find the target by name
        target = None
        for t in settings.ingestion_targets:
            if t.name == target_name:
                target = t
                break
        
        if not target:
            console.print(f"[red]Target '{target_name}' not found in configuration.[/red]")
            console.print(f"[blue]Available targets:[/blue] {', '.join([t.name for t in settings.ingestion_targets])}")
            raise typer.Exit(1)
        
        if not target.enabled:
            console.print(f"[yellow]Target '{target_name}' is disabled.[/yellow]")
            raise typer.Exit(1)
        
        sources = [target.url]
        console.print(f"[blue]Using configured target:[/blue] {target.name}")
    elif all_targets:
        enabled_targets = settings.get_enabled_targets()
        if not enabled_targets:
            console.print("[yellow]No enabled targets found in configuration.[/yellow]")
            raise typer.Exit(1)
        
        sources = [target.url for target in enabled_targets]
        console.print(f"[blue]Using {len(enabled_targets)} enabled targets from configuration.[/blue]")

    if not sources:
        console.print("[red]No valid DBLP sources provided.[/red]")
        raise typer.Exit(1)

    if resume_task:
        task = manager.resume(resume_task)
        if task is None:
            console.print(f"[red]Task {resume_task} not found.[/red]")
            raise typer.Exit(1)
    else:
        task = manager.enqueue(
            "dblp_ingest",
            payload={
                "sources": sources,
                "max_entries": max_entries,
            },
        )

    console.print(f"[green]Starting fetch task:[/green] {task.task_id}")
    
    for pending in manager.drain():
        if pending.task_id != task.task_id:
            continue
        runner.run(manager, pending)
        break


@app.command()
def query(
    prompt: str = typer.Argument(..., help="Search intent expressed in natural language"),
    top_k: int = typer.Option(10, "--top-k", help="Number of results to return"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table")
):
    """Rank stored papers against a natural language query using AI."""
    settings = Settings()
    store = PaperStore(settings)
    papers = store.list()
    
    if not papers:
        console.print("[red]No papers stored. Run the fetch command first.[/red]")
        raise typer.Exit(1)

    console.print(f"[blue]Querying {len(papers)} papers with prompt:[/blue] '{prompt}'")
    
    client = DeepSeekClient(settings)
    ranked = client.rank_papers(prompt, papers, top_k=top_k)
    
    if json_output:
        print(json.dumps([item.to_dict() for item in ranked], ensure_ascii=False, indent=2))
    else:
        _print_ranked_table(ranked)


@app.command()
def tasks():
    """List known tasks and their status."""
    settings = Settings()
    manager = TaskManager(settings=settings)
    tasks = manager.store.list()
    
    if not tasks:
        console.print("[yellow]No tasks recorded yet.[/yellow]")
        return
    
    table = Table(title="Task Status")
    table.add_column("Task ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Type", style="blue")
    table.add_column("Progress", style="yellow")
    
    for task in tasks:
        progress = f"{task.progress}/{task.total or '?'}"
        table.add_row(task.task_id, task.status.value, task.task_type, progress)
    
    console.print(table)


@app.command()
def remove(
    pattern: Optional[str] = typer.Option(None, "--pattern", help="Pattern to match source URLs (case-insensitive)"),
    source_url: Optional[str] = typer.Option(None, "--source-url", help="Exact source URL to remove"),
    target_name: Optional[str] = typer.Option(None, "--target", help="Name of a configured ingestion target to remove"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted without actually deleting"),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt")
):
    """Remove ingestion states and papers."""
    # Count how many removal options are provided
    removal_options = sum([bool(pattern), bool(source_url), bool(target_name)])
    
    if removal_options == 0:
        console.print("[red]Error:[/red] Must specify one of --pattern, --source-url, or --target")
        raise typer.Exit(1)
    
    if removal_options > 1:
        console.print("[red]Error:[/red] Can only specify one removal option at a time")
        raise typer.Exit(1)

    settings = Settings()
    state_store = IngestionStateStore(settings)
    paper_store = PaperStore(settings)
    
    # Determine sources to delete
    sources_to_delete = []
    
    if pattern:
        states = state_store.list()
        matching_sources = [state.source_url for state in states if pattern.lower() in state.source_url.lower()]
        sources_to_delete = matching_sources
        console.print(f"[blue]Found {len(matching_sources)} sources matching pattern '{pattern}':[/blue]")
        for source in matching_sources:
            console.print(f"  {source}")
    
    elif source_url:
        states = state_store.list()
        if source_url in [state.source_url for state in states]:
            sources_to_delete = [source_url]
            console.print(f"[blue]Found source:[/blue] {source_url}")
        else:
            console.print(f"[yellow]Source URL '{source_url}' not found in ingestion states.[/yellow]")
            return
    
    elif target_name:
        # Find the target by name
        target = None
        for t in settings.ingestion_targets:
            if t.name == target_name:
                target = t
                break
        
        if not target:
            console.print(f"[red]Target '{target_name}' not found in configuration.[/red]")
            console.print(f"[blue]Available targets:[/blue] {', '.join([t.name for t in settings.ingestion_targets])}")
            raise typer.Exit(1)
        
        sources_to_delete = [target.url]
        console.print(f"[blue]Removing target:[/blue] {target.name}")
        
        # Also remove from configuration
        if settings.remove_ingestion_target(target_name):
            settings.save_to_yaml()  # Automatically save changes
            console.print(f"[green]Removed target '{target_name}' from configuration.[/green]")
        else:
            console.print(f"[yellow]Target '{target_name}' not found in configuration.[/yellow]")
    
    if not sources_to_delete:
        console.print("[yellow]No matching sources found.[/yellow]")
        return
    
    # Count papers that would be deleted
    papers = paper_store.list()
    papers_to_delete = [paper for paper in papers if paper.source in sources_to_delete]
    
    console.print(f"\n[red]Would delete {len(papers_to_delete)} papers from {len(sources_to_delete)} sources.[/red]")
    
    if dry_run:
        console.print("[yellow]Dry run mode - no changes made.[/yellow]")
        return
    
    # Confirm deletion unless forced
    if not force:
        if not typer.confirm("Are you sure you want to delete these sources and papers?"):
            console.print("[yellow]Operation cancelled.[/yellow]")
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
    
    console.print(f"[green]Successfully deleted {deleted_states} ingestion states and {deleted_papers} papers.[/green]")


@app.command()
def config(
    init: bool = typer.Option(False, "--init", help="Initialize a default config.yaml file"),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
    add_target: Optional[str] = typer.Option(None, "--add-target", help="Add a new ingestion target (format: name:url)"),
    list_targets: bool = typer.Option(False, "--list-targets", help="List all configured ingestion targets")
):
    """Manage configuration settings."""
    settings = Settings()
    
    if init:
        try:
            settings.create_default_config()
            console.print(f"[green]Created default configuration at {settings.config_file}[/green]")
        except Exception as e:
            console.print(f"[red]Failed to create default config:[/red] {e}")
            raise typer.Exit(1)
    
    elif show:
        console.print(f"[blue]Configuration file:[/blue] {settings.config_file}")
        console.print(f"[blue]DeepSeek API Key:[/blue] {'*' * 20 if settings.deepseek_api_key else 'Not set'}")
        console.print(f"[blue]DeepSeek API Base:[/blue] {settings.deepseek_api_base}")
        console.print(f"[blue]DeepSeek Model:[/blue] {settings.deepseek_model}")
        console.print(f"[blue]Data Directory:[/blue] {settings.data_dir}")
        console.print(f"[blue]Ingestion Targets:[/blue] {len(settings.ingestion_targets)}")
    
    elif add_target:
        try:
            # Parse format: name:url
            # Handle URLs with :// by finding the first colon
            if '://' in add_target:
                # Split by first colon only
                parts = add_target.split(':', 1)
                if len(parts) != 2:
                    console.print("[red]Error:[/red] Target format should be 'name:url'")
                    raise typer.Exit(1)
                name, url = parts[0], parts[1]
            else:
                # No :// in the string, use simple split
                parts = add_target.split(':', 1)
                if len(parts) != 2:
                    console.print("[red]Error:[/red] Target format should be 'name:url'")
                    raise typer.Exit(1)
                name, url = parts[0], parts[1]
            
            settings.add_ingestion_target(name, url)
            settings.save_to_yaml()  # Automatically save changes
            console.print(f"[green]Added target:[/green] {name}")
        except Exception as e:
            console.print(f"[red]Failed to add target:[/red] {e}")
            raise typer.Exit(1)
    
    elif list_targets:
        if not settings.ingestion_targets:
            console.print("[yellow]No ingestion targets configured.[/yellow]")
            return
        
        table = Table(title="Configured Ingestion Targets")
        table.add_column("Name", style="cyan")
        table.add_column("URL", style="blue", max_width=60)
        table.add_column("Enabled", style="yellow")
        
        for target in settings.ingestion_targets:
            table.add_row(
                target.name,
                target.url,
                "✓" if target.enabled else "✗"
            )
        
        console.print(table)
    
    else:
        console.print("[yellow]Use --help to see available config options.[/yellow]")


@app.command()
def sync():
    """Sync current local ingestion states back to YAML configuration."""
    settings = Settings()
    state_store = IngestionStateStore(settings)
    
    # Get current ingestion states from local storage
    current_states = state_store.list()
    
    if not current_states:
        console.print("[yellow]No ingestion states found to sync.[/yellow]")
        return
    
    console.print(f"[blue]Found {len(current_states)} ingestion states to sync:[/blue]")
    
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
            target = IngestionTarget(
                name=name,
                url=state.source_url,
                enabled=True
            )
            settings.ingestion_targets.append(target)
            synced_targets.append(f"[green]Added:[/green] {name}")
        else:
            # Update existing target
            synced_targets.append(f"[blue]Updated:[/blue] {name}")
    
    # Save updated configuration
    try:
        settings.save_to_yaml()
        console.print(f"[green]Configuration synced to {settings.config_file}[/green]")
        console.print(f"[green]Synced {len(synced_targets)} targets:[/green]")
        for target_info in synced_targets:
            console.print(f"  {target_info}")
    except Exception as e:
        console.print(f"[red]Failed to sync configuration:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def list(
    sources: bool = typer.Option(False, "--sources", help="List ingestion sources"),
    papers: bool = typer.Option(False, "--papers", help="List papers"),
    authors: bool = typer.Option(False, "--authors", help="List authors"),
    limit: int = typer.Option(20, "--limit", help="Limit number of results"),
    pattern: Optional[str] = typer.Option(None, "--pattern", help="Filter by pattern (case-insensitive)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON")
):
    """List various data stored by paperfinder."""
    if not sources and not papers and not authors:
        console.print("[red]Error:[/red] Must specify one of --sources, --papers, or --authors")
        raise typer.Exit(1)
    
    if sum([sources, papers, authors]) > 1:
        console.print("[red]Error:[/red] Can only specify one of --sources, --papers, or --authors")
        raise typer.Exit(1)

    settings = Settings()
    state_store = IngestionStateStore(settings)
    paper_store = PaperStore(settings)
    
    if sources:
        states = state_store.list()
        if pattern:
            states = [state for state in states if pattern.lower() in state.source_url.lower()]
        
        states = states[:limit]
        
        if json_output:
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
                console.print("[yellow]No ingestion sources found.[/yellow]")
                return
            
            table = Table(title=f"Ingestion Sources (showing {len(states)})")
            table.add_column("Source URL", style="cyan")
            table.add_column("Offset", style="blue")
            table.add_column("Collected", style="green")
            table.add_column("Available", style="yellow")
            table.add_column("Updated", style="magenta")
            
            for state in states:
                table.add_row(
                    state.source_url,
                    str(state.offset),
                    str(state.total_collected),
                    str(state.total_available),
                    str(state.updated_at)
                )
            
            console.print(table)
    
    elif papers:
        papers = paper_store.list()
        if pattern:
            papers = [paper for paper in papers if pattern.lower() in paper.title.lower()]
        
        papers = papers[:limit]
        
        if json_output:
            output = [paper.to_dict() for paper in papers]
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not papers:
                console.print("[yellow]No papers found.[/yellow]")
                return
            
            table = Table(title=f"Papers (showing {len(papers)})")
            table.add_column("Title", style="cyan", max_width=50)
            table.add_column("Authors", style="blue", max_width=30)
            table.add_column("Venue", style="green", max_width=20)
            table.add_column("Year", style="yellow")
            table.add_column("DOI", style="magenta", max_width=20)
            
            for paper in papers:
                authors = ", ".join(paper.authors[:3])
                if len(paper.authors) > 3:
                    authors += f" (+{len(paper.authors) - 3} more)"
                
                table.add_row(
                    paper.title,
                    authors,
                    paper.venue or "N/A",
                    str(paper.year) if paper.year else "N/A",
                    paper.doi or "N/A"
                )
            
            console.print(table)
    
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
            output = [{"author": author, "paper_count": count} for author, count in sorted_authors]
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            if not sorted_authors:
                console.print("[yellow]No authors found.[/yellow]")
                return
            
            table = Table(title=f"Authors (showing {len(sorted_authors)})")
            table.add_column("Author", style="cyan")
            table.add_column("Paper Count", style="green")
            
            for author, count in sorted_authors:
                table.add_row(author, str(count))
            
            console.print(table)


def _print_ranked_table(ranked) -> None:
    """Print ranked papers in a nice table format."""
    table = Table(title="Query Results")
    table.add_column("Rank", style="cyan", width=6)
    table.add_column("Title", style="blue", max_width=50)
    table.add_column("Authors", style="green", max_width=30)
    table.add_column("Venue", style="yellow", max_width=20)
    table.add_column("Score", style="red", width=8)
    table.add_column("Reason", style="magenta", max_width=30)
    
    for idx, item in enumerate(ranked, start=1):
        paper: Paper = item.paper
        authors = ", ".join(paper.authors[:3])
        if len(paper.authors) > 3:
            authors += f" (+{len(paper.authors) - 3} more)"
        
        table.add_row(
            str(idx),
            paper.title,
            authors,
            paper.venue or "N/A",
            f"{item.score:.3f}",
            item.reason or ""
        )
    
    console.print(table)


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
    app(argv)


if __name__ == "__main__":  # pragma: no cover
    main()