"""DeepSeek integration for relevance scoring."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings
from .models import Paper


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"\W+", text.lower()) if token]


@dataclass(slots=True)
class RankedPaper:
    paper: Paper
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        payload = self.paper.to_dict()
        payload["score"] = self.score
        payload["reason"] = self.reason
        return payload


class DeepSeekClient:
    """Client for DeepSeek language model with graceful degradation."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        timeout: int = 60,
    ) -> None:
        self.settings = settings or Settings()
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    def rank_papers(
        self,
        query: str,
        papers: Iterable[Paper],
        *,
        top_k: int = 10,
    ) -> list[RankedPaper]:
        paper_list = list(papers)
        if not paper_list:
            return []

        if not self.is_configured:
            return self._fallback_rank(query, paper_list, top_k=top_k)

        try:
            return self._remote_rank(query, paper_list, top_k=top_k)
        except Exception:  # pragma: no cover - defensive guard
            return self._fallback_rank(query, paper_list, top_k=top_k)

    def _fallback_rank(
        self,
        query: str,
        papers: list[Paper],
        *,
        top_k: int,
    ) -> list[RankedPaper]:
        print("Performing keyword-based ranking...")
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
            else:
                overlap = len(tokens.intersection(query_tokens))
                score = overlap / math.sqrt(len(tokens) or 1)
            reason = f"Keyword overlap: {len(tokens.intersection(query_tokens))} shared terms."
            ranked.append(RankedPaper(paper=paper, score=score, reason=reason))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _remote_rank(
        self,
        query: str,
        papers: list[Paper],
        *,
        top_k: int,
    ) -> list[RankedPaper]:
        print("Sending request to DeepSeek API...")
        request_payload = self._build_prompt(query, papers, top_k=top_k)
        endpoint = f"{self.settings.deepseek_api_base.rstrip('/')}/chat/completions"
        request = Request(
            endpoint,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:  # pragma: no cover - network specific
            raise RuntimeError(f"DeepSeek HTTP error {exc.code}: {exc.reason}") from exc
        except URLError as exc:  # pragma: no cover - network specific
            raise RuntimeError(f"DeepSeek network error: {exc.reason}") from exc
        
        print("Processing API response...")

        message = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            structured = json.loads(message)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DeepSeek returned non-JSON content.") from exc

        ranked: list[RankedPaper] = []
        results = structured.get("results", [])
        
        for item in results:
            paper_id = item.get("id")
            score = float(item.get("score", 0.0))
            reason = item.get("reason", "")
            match = next(
                (paper for paper in papers if paper.identifier == paper_id), None
            )
            if match is None:
                continue
            ranked.append(RankedPaper(paper=match, score=score, reason=reason))
        ranked.sort(key=lambda entry: entry.score, reverse=True)
        return ranked[:top_k]

    def _build_prompt(
        self,
        query: str,
        papers: list[Paper],
        *,
        top_k: int,
    ) -> dict[str, Any]:
        documents = [
            {
                "id": paper.identifier,
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "venue": paper.venue,
                "year": paper.year,
                "doi": paper.doi,
            }
            for paper in papers
        ]
        system_prompt = (
            "You are a research assistant. You receive a JSON list of papers and "
            "must rank them by relevance to the user query. Respond strictly in JSON format with the following structure:\n"
            '{"results": [{"id": "paper_id", "score": 0.95, "reason": "explanation"}]}\n'
            "Score should be between 0.0 and 1.0, with higher scores indicating better relevance."
        )
        user_prompt = {
            "query": query,
            "top_k": top_k,
            "papers": documents,
        }
        return {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
