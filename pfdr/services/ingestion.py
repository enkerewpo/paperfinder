"""Domain services for ingestion workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from ..config import IngestionTarget, Settings
from ..dblp import DblpIngestionTaskRunner
from ..models import Paper
from ..state import IngestionStateStore, SourceIngestionState
from ..storage import PaperStore
from ..tasks import TaskManager, TaskMeta


class SourceSelectionError(ValueError):
    """Raised when the caller provides an invalid source selection."""


@dataclass(slots=True)
class FetchOptions:
    """User-provided options for running a fetch task."""

    source_url: str | None = None
    sources_file: str | None = None
    target_name: str | None = None
    all_targets: bool = False
    page_size: int = 200
    max_entries: int | None = None
    resume_task: str | None = None


@dataclass(slots=True)
class FetchSummary:
    """Detailed information about a fetch execution."""

    task: TaskMeta
    sources: Sequence[str]
    initial_paper_count: int
    final_paper_count: int

    @property
    def new_papers(self) -> int:
        return self.final_paper_count - self.initial_paper_count


@dataclass(slots=True)
class RemovalOptions:
    """Options supplied by the CLI for deletion flows."""

    pattern: str | None = None
    source_url: str | None = None
    target_name: str | None = None


@dataclass(slots=True)
class RemovalPlan:
    """Calculated plan describing the sources and papers that will be deleted."""

    sources: list[str]
    papers: list[Paper]
    state_urls: list[str]

    @property
    def deleted_count(self) -> int:
        return len(self.papers)

    @property
    def state_count(self) -> int:
        return len(self.state_urls)

    def is_empty(self) -> bool:
        return not self.sources


class IngestionService:
    """Coordinates ingestion, removal and sync workflows."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        task_manager: TaskManager | None = None,
        paper_store: PaperStore | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.task_manager = task_manager or TaskManager(self.settings)
        self.paper_store = paper_store or PaperStore(self.settings)

    def run_fetch(
        self, options: FetchOptions, *, sources: list[str] | None = None
    ) -> FetchSummary:
        resolved_sources = sources or self.resolve_sources(options)
        runner = DblpIngestionTaskRunner(
            settings=self.settings, page_size=options.page_size
        )

        task = self._resolve_task(options, resolved_sources)
        initial_paper_count = len(self.paper_store.list())

        for pending in self.task_manager.drain():
            if pending.task_id != task.task_id:
                continue
            runner.run(self.task_manager, pending)
            break

        final_paper_count = len(self.paper_store.list())
        return FetchSummary(
            task=task,
            sources=resolved_sources,
            initial_paper_count=initial_paper_count,
            final_paper_count=final_paper_count,
        )

    def resolve_sources(self, options: FetchOptions) -> list[str]:
        return self._determine_sources(options)

    def plan_removal(self, options: RemovalOptions) -> RemovalPlan:
        state_store = IngestionStateStore(self.settings)
        states = state_store.list()
        sources = self._determine_removal_sources(options, states=states)
        papers = [paper for paper in self.paper_store.list() if paper.source in sources]
        state_urls = [
            state.source_url for state in states if state.source_url in sources
        ]
        return RemovalPlan(sources=sources, papers=papers, state_urls=state_urls)

    def apply_removal(self, plan: RemovalPlan) -> tuple[int, int]:
        if plan.is_empty():
            return (0, 0)

        state_store = IngestionStateStore(self.settings)
        deleted_states = 0
        for source in plan.state_urls:
            deleted_states += int(state_store.delete_by_source(source))

        deleted_papers = self.paper_store.delete_by_sources(plan.sources)
        return deleted_states, deleted_papers

    def sync_to_config(self) -> tuple[int, list[str]]:
        state_store = IngestionStateStore(self.settings)
        current_states = state_store.list()
        synced_targets: list[str] = []

        for state in current_states:
            name = self._extract_target_name_from_url(state.source_url)
            existing = self._find_target_by_url(state.source_url)
            if existing is None:
                self.settings.ingestion_targets.append(
                    IngestionTarget(name=name, url=state.source_url, enabled=True)
                )
                synced_targets.append(f"Added: {name}")
            else:
                existing.enabled = True
                synced_targets.append(f"Updated: {name}")

        if synced_targets:
            self.settings.save_to_yaml()

        return len(synced_targets), synced_targets

    # Internal helpers -------------------------------------------------

    def _determine_sources(self, options: FetchOptions) -> list[str]:
        provided = [
            bool(options.source_url),
            bool(options.sources_file),
            bool(options.target_name),
            bool(options.all_targets),
        ]

        if sum(provided) == 0:
            raise SourceSelectionError(
                "One of source_url, sources_file, target_name or all_targets must be provided"
            )
        if sum(provided) > 1:
            raise SourceSelectionError("Multiple source options supplied")

        if options.source_url:
            return [options.source_url]
        if options.sources_file:
            return self._load_sources_file(options.sources_file)
        if options.target_name:
            target = self._find_target_by_name(options.target_name)
            if target is None:
                raise SourceSelectionError(
                    f"Target '{options.target_name}' not found in configuration"
                )
            if not target.enabled:
                raise SourceSelectionError(
                    f"Target '{options.target_name}' is disabled"
                )
            return [target.url]
        enabled_targets = self.settings.get_enabled_targets()
        if not enabled_targets:
            raise SourceSelectionError("No enabled targets found in configuration")
        return [target.url for target in enabled_targets]

    def _resolve_task(self, options: FetchOptions, sources: Iterable[str]) -> TaskMeta:
        if options.resume_task:
            task = self.task_manager.resume(options.resume_task)
            if task is None:
                raise SourceSelectionError(
                    f"Task {options.resume_task} not found for resumption"
                )
            return task

        payload = {"sources": list(sources), "max_entries": options.max_entries}
        return self.task_manager.enqueue("dblp_ingest", payload=payload)

    def _determine_removal_sources(
        self,
        options: RemovalOptions,
        *,
        states: list[SourceIngestionState] | None = None,
    ) -> list[str]:
        provided = [
            bool(options.pattern),
            bool(options.source_url),
            bool(options.target_name),
        ]
        if sum(provided) == 0:
            raise SourceSelectionError(
                "One of pattern, source_url or target_name must be provided"
            )
        if sum(provided) > 1:
            raise SourceSelectionError("Multiple removal selectors supplied")

        state_records = states or IngestionStateStore(self.settings).list()

        if options.pattern:
            pattern = options.pattern.lower()
            return [
                state.source_url
                for state in state_records
                if pattern in state.source_url.lower()
            ]
        if options.source_url:
            urls = [state.source_url for state in state_records]
            if options.source_url not in urls:
                return []
            return [options.source_url]
        target = self._find_target_by_name(options.target_name or "")
        if target is None:
            raise SourceSelectionError(
                f"Target '{options.target_name}' not found in configuration"
            )
        return [target.url]

    def _find_target_by_name(self, name: str) -> IngestionTarget | None:
        for target in self.settings.ingestion_targets:
            if target.name == name:
                return target
        return None

    def _find_target_by_url(self, url: str) -> IngestionTarget | None:
        for target in self.settings.ingestion_targets:
            if target.url == url:
                return target
        return None

    def _load_sources_file(self, path: str) -> list[str]:
        content = Path(path).read_text(encoding="utf-8")
        sources: list[str] = []
        for line in content.splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            if candidate not in sources:
                sources.append(candidate)
        if not sources:
            raise SourceSelectionError(f"No valid sources found in file: {path}")
        return sources

    def _extract_target_name_from_url(self, url: str) -> str:
        if "stream:conf/" in url:
            parts = url.split("stream:conf/")[1].split(":")
            if len(parts) >= 2:
                conf_name = parts[0]
                year = parts[1].split("&")[0]
                return f"{conf_name}-{year}"
        if "stream:journals/" in url:
            parts = url.split("stream:journals/")[1].split(":")
            if len(parts) >= 2:
                journal_name = parts[0]
                year = parts[1].split("&")[0]
                return f"{journal_name}-{year}"
        from hashlib import md5

        return f"target-{md5(url.encode()).hexdigest()[:8]}"
