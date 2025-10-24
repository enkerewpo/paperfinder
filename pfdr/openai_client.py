"""OpenAI integration for relevance scoring."""

from __future__ import annotations

import json
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings
from .llm import RankedPaper, keyword_rank
from .models import Paper


class OpenAIClient:
    """Client for OpenAI-compatible chat completion models."""

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
        return bool(self.settings.llm_api_key)

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
        return keyword_rank(query, papers, top_k=top_k)

    def _remote_rank(
        self,
        query: str,
        papers: list[Paper],
        *,
        top_k: int,
    ) -> list[RankedPaper]:
        print("Sending request to OpenAI API...")
        request_payload = self._build_prompt(query, papers, top_k=top_k)
        api_base = (self.settings.llm_api_base or "https://api.openai.com/v1").rstrip(
            "/"
        )
        endpoint = f"{api_base}/chat/completions"
        request = Request(
            endpoint,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:  # pragma: no cover - network specific
            raise RuntimeError(f"OpenAI HTTP error {exc.code}: {exc.reason}") from exc
        except URLError as exc:  # pragma: no cover - network specific
            raise RuntimeError(f"OpenAI network error: {exc.reason}") from exc

        message = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            structured = json.loads(message)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI returned non-JSON content.") from exc

        ranked: list[RankedPaper] = []
        for item in structured.get("results", []):
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
    ) -> dict[str, object]:
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
            "must rank them by relevance to the user query. Respond strictly in JSON "
            "format with the following structure:\n"
            '{"results": [{"id": "paper_id", "score": 0.95, "reason": "explanation"}]}\n'
            "Score should be between 0.0 and 1.0, with higher scores indicating better relevance."
        )

        user_prompt = {
            "query": query,
            "top_k": top_k,
            "papers": documents,
        }

        return {
            "model": self.settings.llm_model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }

    async def chat_completion(
        self, messages: list[dict], temperature: float = 0.7
    ) -> str:
        """Chat completion method for enrichment services."""
        if not self.is_configured:
            return "OpenAI API not configured"

        try:
            request_payload = {
                "model": self.settings.llm_model or "gpt-4o-mini",
                "messages": messages,
                "temperature": temperature,
            }

            api_base = (
                self.settings.llm_api_base or "https://api.openai.com/v1"
            ).rstrip("/")
            endpoint = f"{api_base}/chat/completions"
            request = Request(
                endpoint,
                data=json.dumps(request_payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
            )

            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))

            return payload.get("choices", [{}])[0].get("message", {}).get("content", "")

        except Exception as e:
            raise RuntimeError(f"OpenAI chat completion error: {e}") from e


__all__ = ["OpenAIClient"]
