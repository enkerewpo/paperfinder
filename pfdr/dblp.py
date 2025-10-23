"""DBLP ingestion utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .config import Settings
from .models import Paper, TaskMeta
from .state import IngestionStateStore, SourceIngestionState
from .storage import PaperStore
from .tasks import TaskManager

USER_AGENT = "pfdr/0.1 (https://github.com/)"


@dataclass(slots=True)
class DblpBatch:
    items: list[dict[str, Any]]
    offset: int
    total: int


class DblpClient:
    """Thin wrapper around the DBLP search API."""

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def fetch_batch(
        self,
        source_url: str,
        *,
        offset: int,
        page_size: int,
    ) -> DblpBatch:
        request_url = self._build_url(source_url, offset=offset, page_size=page_size)
        request = Request(
            request_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"DBLP returned HTTP {exc.code}: {exc.reason}") from exc
        except URLError as exc:
            raise RuntimeError(f"Unable to reach DBLP: {exc.reason}") from exc

        hits = payload.get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        total = int(payload.get("result", {}).get("hits", {}).get("@total", len(hits)))
        return DblpBatch(items=list(hits or []), offset=offset, total=total)

    @staticmethod
    def _build_url(source_url: str, *, offset: int, page_size: int) -> str:
        parsed = urlparse(source_url)
        query_params = dict(parse_qsl(parsed.query))
        query_params.setdefault("format", "json")
        query_params["h"] = str(page_size)
        query_params["f"] = str(offset)
        encoded = urlencode(query_params)
        return urlunparse(parsed._replace(query=encoded))

    def to_paper(self, raw_entry: dict[str, Any], *, source_url: str) -> Paper:
        info = raw_entry.get("info", {})
        authors_block = info.get("authors") or {}
        raw_authors = authors_block.get("author")
        if raw_authors is None:
            authors: list[str] = []
        elif isinstance(raw_authors, list):
            authors = [
                author.get("text") if isinstance(author, dict) else str(author)
                for author in raw_authors
            ]
        elif isinstance(raw_authors, dict):
            authors = [raw_authors.get("text") or raw_authors.get("@pid", "")]
        else:
            authors = [str(raw_authors)]

        doi = info.get("doi")
        if isinstance(doi, list):
            doi = doi[0]

        return Paper(
            identifier=info.get("key") or info.get("url") or "",
            title=info.get("title", "").strip(),
            authors=[author for author in authors if author],
            year=int(info["year"])
            if "year" in info and str(info["year"]).isdigit()
            else None,
            doi=doi,
            url=info.get("ee") or info.get("url"),
            abstract=info.get("abstract"),
            venue=info.get("venue"),
            source=source_url,
        )


class DblpIngestionTaskRunner:
    """Execute a DBLP ingestion task with checkpointing and source sync."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        page_size: int = 200,
        client: DblpClient | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.page_size = page_size
        self.client = client or DblpClient()
        self.store = PaperStore(self.settings)
        self.state_store = IngestionStateStore(self.settings)

    def run(self, manager: TaskManager, task: TaskMeta) -> None:
        payload = task.payload or {}
        sources = self._resolve_sources(payload)
        if not sources:
            raise ValueError("DBLP ingestion task requires at least one source URL.")

        max_entries = payload.get("max_entries")
        if max_entries is not None:
            max_entries = int(max_entries)

        checkpoint = task.checkpoint or {}
        checkpoint_sources: dict[str, dict[str, int | None]] = dict(
            checkpoint.get("sources", {})
        )
        overall_collected = int(checkpoint.get("overall_collected", 0))

        known_ids = self.store.identifiers_by_source()
        state_index = {state.source_url: state for state in self.state_store.list()}

        with manager.run_task(
            task,
            total=self._compute_total_hint(
                checkpoint_sources, max_entries, len(sources)
            ),
        ) as progress_update:
            print(f"Processing {len(sources)} sources...")
            for source_idx, source_url in enumerate(sources, 1):
                print(f"Source {source_idx}/{len(sources)}: {source_url}")
                state = state_index.get(source_url)
                source_checkpoint = checkpoint_sources.get(source_url, {})

                offset = max(
                    int(source_checkpoint.get("offset", 0) or 0),
                    state.offset if state else 0,
                )
                collected = max(
                    int(source_checkpoint.get("collected", 0) or 0),
                    state.total_collected if state else 0,
                )
                total_available = source_checkpoint.get("total_available")
                if total_available is None and state:
                    total_available = state.total_available

                source_known = known_ids.setdefault(source_url, set())

                batch_count = 0
                while True:
                    if max_entries is not None and collected >= max_entries:
                        break
                    batch_size = self._compute_batch_size(max_entries, collected)
                    batch_count += 1

                    print(
                        f"  Fetching batch {batch_count} (offset: {offset}, size: {batch_size})..."
                    )
                    batch = self.client.fetch_batch(
                        source_url, offset=offset, page_size=batch_size
                    )
                    if not batch.items:
                        break

                    papers = [
                        self.client.to_paper(entry, source_url=source_url)
                        for entry in batch.items
                    ]
                    new_papers = [
                        paper
                        for paper in papers
                        if paper.identifier not in source_known
                    ]

                    if new_papers:
                        self.store.upsert_many(new_papers)
                        source_known.update(paper.identifier for paper in new_papers)
                        collected += len(new_papers)
                        overall_collected += len(new_papers)
                        print(
                            f"  Added {len(new_papers)} new papers (total for this source: {collected})"
                        )
                    else:
                        print(f"  No new papers in this batch")

                    offset += len(batch.items)
                    total_available = batch.total

                    checkpoint_sources[source_url] = {
                        "offset": offset,
                        "collected": collected,
                        "total_available": total_available,
                    }

                    total_hint = self._compute_total_hint(
                        checkpoint_sources, max_entries, len(sources)
                    )
                    progress_update(
                        overall_collected,
                        total_hint,
                        {
                            "sources": dict(checkpoint_sources),
                            "overall_collected": overall_collected,
                        },
                    )

                    if len(batch.items) < batch_size:
                        break
                    if (
                        not new_papers
                        and total_available is not None
                        and offset >= int(total_available)
                    ):
                        break

                self.state_store.upsert(
                    SourceIngestionState(
                        source_url=source_url,
                        offset=offset,
                        total_collected=collected,
                        total_available=total_available,
                    )
                )

                # Show source completion summary
                print(
                    f"  Source completed: {collected} papers collected, offset: {offset}"
                )

    def _compute_batch_size(self, max_entries: int | None, collected: int) -> int:
        if max_entries is None:
            return self.page_size
        remaining = max(max_entries - collected, 0)
        return min(self.page_size, remaining) if remaining else self.page_size

    @staticmethod
    def _compute_total_hint(
        sources_state: dict[str, dict[str, int | None]],
        max_entries: int | None,
        source_count: int,
    ) -> int | None:
        if max_entries is not None:
            return max_entries * source_count
        totals: list[int] = []
        for state in sources_state.values():
            total = state.get("total_available")
            if total is None:
                return None
            totals.append(int(total))
        return sum(totals) if totals else None

    @staticmethod
    def _resolve_sources(payload: dict[str, Any]) -> list[str]:
        sources: list[str] = []
        if "sources" in payload and isinstance(payload["sources"], list):
            sources.extend(str(item).strip() for item in payload["sources"])
        elif payload.get("source_url"):
            sources.append(str(payload["source_url"]).strip())

        cleaned: list[str] = []
        seen: set[str] = set()
        for candidate in sources:
            if not candidate:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            cleaned.append(candidate)
        return cleaned
