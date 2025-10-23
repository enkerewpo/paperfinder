"""Persistent tracking for DBLP source ingestion progress."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .config import Settings
from .storage import FileLock


@dataclass(slots=True)
class SourceIngestionState:
    """Track per-source offsets to avoid re-fetching processed pages."""

    source_url: str
    offset: int = 0
    total_collected: int = 0
    total_available: int | None = None
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "offset": self.offset,
            "total_collected": self.total_collected,
            "total_available": self.total_available,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceIngestionState":
        return cls(
            source_url=payload["source_url"],
            offset=int(payload.get("offset", 0)),
            total_collected=int(payload.get("total_collected", 0)),
            total_available=payload.get("total_available"),
            updated_at=payload.get("updated_at")
            or datetime.utcnow().isoformat(),
        )


class IngestionStateStore:
    """Disk-backed store for ingestion offsets."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = FileLock()
        self.settings.ensure_data_dir()

    def _load(self) -> dict[str, SourceIngestionState]:
        path = self.settings.ingestion_state_path
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except json.JSONDecodeError:
                payload = {}
        return {
            source_url: SourceIngestionState.from_dict(state)
            for source_url, state in payload.items()
        }

    def _persist(self, states: dict[str, SourceIngestionState]) -> None:
        path = self.settings.ingestion_state_path
        with path.open("w", encoding="utf-8") as fh:
            json.dump(
                {source: state.to_dict() for source, state in states.items()},
                fh,
                ensure_ascii=False,
                indent=2,
            )

    def get(self, source_url: str) -> SourceIngestionState | None:
        return self._load().get(source_url)

    def upsert(self, state: SourceIngestionState) -> SourceIngestionState:
        with self._lock:
            states = self._load()
            state.updated_at = datetime.utcnow().isoformat()
            states[state.source_url] = state
            self._persist(states)
        return state

    def list(self) -> list[SourceIngestionState]:
        return list(self._load().values())

    def delete_by_pattern(self, pattern: str) -> list[str]:
        """Delete ingestion states matching a pattern and return deleted source URLs."""
        with self._lock:
            states = self._load()
            deleted_sources = []
            
            # Find matching sources
            for source_url in list(states.keys()):
                if pattern.lower() in source_url.lower():
                    deleted_sources.append(source_url)
                    del states[source_url]
            
            if deleted_sources:
                self._persist(states)
            
            return deleted_sources

    def delete_by_source(self, source_url: str) -> bool:
        """Delete a specific source URL from ingestion state."""
        with self._lock:
            states = self._load()
            if source_url in states:
                del states[source_url]
                self._persist(states)
                return True
            return False
