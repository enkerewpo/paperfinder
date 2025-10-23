"""Search and reporting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..models import Paper
from ..storage import PaperStore
from ..config import Settings
from ..llm import AdaptiveLLMClient, RankedPaper, create_llm_client


@dataclass(slots=True)
class QueryOptions:
    """Parameters that influence search behaviour."""

    prompt: str
    top_k: int = 10


class QueryService:
    """High level operations for querying stored papers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.paper_store = PaperStore(self.settings)
        self.client: AdaptiveLLMClient = create_llm_client(self.settings)

    def rank(
        self, options: QueryOptions, *, papers: Sequence[Paper] | None = None
    ) -> Sequence[RankedPaper]:
        paper_list = list(papers) if papers is not None else self.paper_store.list()
        if not paper_list:
            return []
        return self.client.rank_papers(options.prompt, paper_list, top_k=options.top_k)

    def list_papers(self) -> list[Paper]:
        return self.paper_store.list()

    def authors_by_frequency(self, pattern: str | None = None) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for paper in self.paper_store.list():
            for author in paper.authors:
                if pattern and pattern.lower() not in author.lower():
                    continue
                counts[author] = counts.get(author, 0) + 1
        return sorted(counts.items(), key=lambda item: item[1], reverse=True)

    def papers_by_sources(self, pattern: str | None = None) -> dict[str, list[Paper]]:
        mapping: dict[str, list[Paper]] = {}
        for paper in self.paper_store.list():
            source = paper.source or ""
            if pattern and pattern.lower() not in source.lower():
                continue
            mapping.setdefault(source, []).append(paper)
        return mapping
