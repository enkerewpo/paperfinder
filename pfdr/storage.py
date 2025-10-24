"""Persistence helpers for papers and tasks."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable

from .config import Settings
from .models import Paper, TaskMeta, TaskStatus


class FileLock:
    """Simple in-process lock for serialized file access."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.release()


class PaperStore:
    """Store papers on disk as JSONL-like records."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = FileLock()
        self.settings.ensure_data_dir()

    def list(self) -> list[Paper]:
        if not self.settings.papers_path.exists():
            return []
        with self.settings.papers_path.open("r", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except json.JSONDecodeError:
                payload = []
        return [Paper.from_dict(entry) for entry in payload]

    def save_all(self, papers: Iterable[Paper]) -> None:
        with self._lock:
            payload = [paper.to_dict() for paper in papers]
            with self.settings.papers_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)

    def update(self, paper: Paper) -> None:
        """Update a single paper in the store."""
        papers = self.list()
        # Find and update the paper
        for i, existing_paper in enumerate(papers):
            if existing_paper.identifier == paper.identifier:
                papers[i] = paper
                break
        else:
            # Paper not found, add it
            papers.append(paper)

        self.save_all(papers)

    def upsert_many(self, papers: Iterable[Paper]) -> list[Paper]:
        existing = {paper.identifier: paper for paper in self.list()}
        changed = False
        for paper in papers:
            current = existing.get(paper.identifier)
            if current == paper:
                continue
            existing[paper.identifier] = paper
            changed = True
        if changed:
            self.save_all(existing.values())
        return list(existing.values())

    def identifiers_by_source(self) -> dict[str, set[str]]:
        mapping: dict[str, set[str]] = {}
        for paper in self.list():
            key = paper.source or ""
            mapping.setdefault(key, set()).add(paper.identifier)
        return mapping

    def delete_by_sources(self, source_urls: list[str]) -> int:
        """Delete papers from specific sources and return count of deleted papers."""
        with self._lock:
            papers = self.list()
            original_count = len(papers)

            # Filter out papers from deleted sources
            filtered_papers = [
                paper for paper in papers if paper.source not in source_urls
            ]

            deleted_count = original_count - len(filtered_papers)

            if deleted_count > 0:
                self.save_all(filtered_papers)

            return deleted_count


class TaskStore:
    """Persist task metadata locally."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = FileLock()
        self.settings.ensure_data_dir()

    def _load(self) -> dict[str, TaskMeta]:
        if not self.settings.tasks_path.exists():
            return {}
        with self.settings.tasks_path.open("r", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except json.JSONDecodeError:
                payload = []
        if isinstance(payload, list):
            payload = {item["task_id"]: item for item in payload}
        return {task_id: TaskMeta.from_dict(data) for task_id, data in payload.items()}

    def _persist(self, tasks: dict[str, TaskMeta]) -> None:
        with self.settings.tasks_path.open("w", encoding="utf-8") as fh:
            json.dump(
                {task_id: task.to_dict() for task_id, task in tasks.items()},
                fh,
                ensure_ascii=False,
                indent=2,
            )

    def list(self) -> list[TaskMeta]:
        return list(self._load().values())

    def get(self, task_id: str) -> TaskMeta | None:
        return self._load().get(task_id)

    def upsert(self, task: TaskMeta) -> TaskMeta:
        with self._lock:
            tasks = self._load()
            tasks[task.task_id] = task
            self._persist(tasks)
        return task

    def by_status(self, status: TaskStatus) -> list[TaskMeta]:
        return [task for task in self.list() if task.status is status]
