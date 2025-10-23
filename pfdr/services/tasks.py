"""Helpers for presenting task information."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..config import Settings
from ..models import TaskMeta
from ..tasks import TaskManager


@dataclass(slots=True)
class TaskView:
    """Human friendly view of a task record."""

    task_id: str
    status: str
    task_type: str
    progress: str


class TaskService:
    """Read-only helper that prepares task information for the CLI."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.manager = TaskManager(self.settings)

    def list_tasks(self) -> Iterable[TaskView]:
        for task in self.manager.store.list():
            total = task.total if task.total is not None else "?"
            if task.progress is None:
                progress = f"?/{total}"
            else:
                progress = f"{task.progress}/{total}"
            yield TaskView(
                task_id=task.task_id,
                status=task.status.value,
                task_type=task.task_type,
                progress=progress,
            )

    def manager_instance(self) -> TaskManager:
        """Expose the underlying manager for operations that require draining."""

        return self.manager
