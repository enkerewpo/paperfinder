"""Shared LLM helpers and adaptive client selection."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from .config import Settings
from .models import Paper


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"\W+", text.lower()) if token]


@dataclass(slots=True)
class RankedPaper:
    """Representation of a ranked paper with metadata for explanations."""

    paper: Paper
    score: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        payload = self.paper.to_dict()
        payload["score"] = self.score
        payload["reason"] = self.reason
        return payload


def keyword_rank(
    query: str, papers: Iterable[Paper], *, top_k: int = 10
) -> list[RankedPaper]:
    """Rank papers by simple keyword overlap as a deterministic fallback."""

    query_tokens = set(_tokenize(query))
    ranked: list[RankedPaper] = []
    for paper in papers:
        text = " ".join(
            filter(
                None,
                [
                    paper.title,
                    " ".join(paper.authors),
                    paper.abstract or "",
                    paper.venue or "",
                ],
            )
        )
        tokens = set(_tokenize(text))
        if not tokens:
            score = 0.0
            overlap = 0
        else:
            overlap = len(tokens.intersection(query_tokens))
            score = overlap / math.sqrt(len(tokens) or 1)
        reason = f"Keyword overlap: {overlap} shared terms."
        ranked.append(RankedPaper(paper=paper, score=score, reason=reason))
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[:top_k]


class KeywordRanker:
    """Fallback ranker that does not require network access."""

    def rank_papers(
        self, query: str, papers: Iterable[Paper], *, top_k: int = 10
    ) -> list[RankedPaper]:
        print("Performing keyword-based ranking...")
        return keyword_rank(query, papers, top_k=top_k)


@runtime_checkable
class SupportsRanking(Protocol):
    """Protocol for provider-specific LLM clients."""

    @property
    def is_configured(self) -> bool: ...

    def rank_papers(
        self, query: str, papers: Iterable[Paper], *, top_k: int = 10
    ) -> list[RankedPaper]: ...


class AdaptiveLLMClient:
    """Wrapper that routes ranking requests to the configured provider."""

    def __init__(
        self,
        backend: SupportsRanking | None,
        *,
        fallback: KeywordRanker | None = None,
    ) -> None:
        self.backend = backend
        self.fallback = fallback or KeywordRanker()

    def rank_papers(
        self, query: str, papers: Iterable[Paper], *, top_k: int = 10
    ) -> list[RankedPaper]:
        paper_list = list(papers)
        if not paper_list:
            return []

        backend = self.backend
        if backend and getattr(backend, "is_configured", False):
            try:
                return backend.rank_papers(query, paper_list, top_k=top_k)
            except Exception:  # pragma: no cover - defensive guard
                pass

        return self.fallback.rank_papers(query, paper_list, top_k=top_k)

    async def chat_completion(self, messages: list[dict], temperature: float = 0.7) -> str:
        """Chat completion method for enrichment services."""
        if self.backend and hasattr(self.backend, 'chat_completion'):
            return await self.backend.chat_completion(messages, temperature=temperature)
        else:
            # Fallback: return a simple response
            return "LLM not configured or available"


def create_llm_client(settings: Settings, *, timeout: int = 60) -> AdaptiveLLMClient:
    """Construct an adaptive client based on configuration."""

    provider = (settings.llm_provider or "deepseek").strip().lower()
    backend: SupportsRanking | None = None

    try:
        if provider in {"deepseek", "deepseek-chat"}:
            from .deepseek import DeepSeekClient

            backend = DeepSeekClient(settings, timeout=timeout)
        elif provider in {"openai", "oai"}:
            from .openai_client import OpenAIClient

            backend = OpenAIClient(settings, timeout=timeout)
    except Exception:  # pragma: no cover - defensive guard
        backend = None

    return AdaptiveLLMClient(backend)


__all__ = [
    "AdaptiveLLMClient",
    "RankedPaper",
    "create_llm_client",
    "keyword_rank",
]

