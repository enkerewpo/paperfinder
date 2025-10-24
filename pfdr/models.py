"""Domain models used by pfdr."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """Lifecycle states persisted for long-running tasks."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class Paper:
    """Lightweight representation of a DBLP entry."""

    identifier: str  # DBLP's key (e.g. 'journals/corr/abs-1234')
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    venue: str | None = None
    source: str | None = None
    keywords: list[str] = field(default_factory=list)  # AI-generated keywords
    category: str | None = None  # AI-generated category/cluster

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "doi": self.doi,
            "url": self.url,
            "abstract": self.abstract,
            "venue": self.venue,
            "source": self.source,
            "keywords": self.keywords,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Paper":
        return cls(
            identifier=payload["id"],
            title=payload["title"],
            authors=list(payload.get("authors") or []),
            year=payload.get("year"),
            doi=payload.get("doi"),
            url=payload.get("url"),
            abstract=payload.get("abstract"),
            venue=payload.get("venue"),
            source=payload.get("source"),
            keywords=list(payload.get("keywords") or []),
            category=payload.get("category"),
        )


@dataclass(slots=True)
class TaskMeta:
    """Persisted metadata for queued work."""

    task_id: str
    task_type: str
    status: TaskStatus
    payload: dict[str, Any] = field(default_factory=dict)
    result_path: str | None = None
    progress: int = 0
    total: int | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "payload": self.payload,
            "result_path": self.result_path,
            "progress": self.progress,
            "total": self.total,
            "checkpoint": self.checkpoint,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskMeta":
        return cls(
            task_id=payload["task_id"],
            task_type=payload["task_type"],
            status=TaskStatus(payload["status"]),
            payload=dict(payload.get("payload") or {}),
            result_path=payload.get("result_path"),
            progress=payload.get("progress", 0),
            total=payload.get("total"),
            checkpoint=dict(payload.get("checkpoint") or {}),
            error=payload.get("error"),
            created_at=payload.get("created_at")
            or datetime.now(timezone.utc).isoformat(),
            updated_at=payload.get("updated_at")
            or datetime.now(timezone.utc).isoformat(),
        )
