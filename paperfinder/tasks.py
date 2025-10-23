"""Task queue, lifecycle management, and resume support."""

from __future__ import annotations

import contextlib
import time
import uuid
from collections import deque
from dataclasses import replace
from typing import Callable, Deque, Iterable, Iterator

from .config import Settings
from .models import TaskMeta, TaskStatus
from .storage import TaskStore

ProgressCallback = Callable[[int, int | None, dict], None]
Checkpoint = dict


class TaskExecutionError(RuntimeError):
    """Raised when task execution fails."""


class TaskManager:
    """Coordinates long-running tasks with persistence."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.store = TaskStore(self.settings)
        self._queue: Deque[TaskMeta] = deque(self.store.list())
        self._rebuild_queue()

    def _rebuild_queue(self) -> None:
        pending = [task for task in self._queue if task.status is TaskStatus.PENDING]
        paused = [task for task in self._queue if task.status is TaskStatus.PAUSED]
        self._queue = deque(pending + paused)

    def enqueue(self, task_type: str, payload: dict | None = None) -> TaskMeta:
        task = TaskMeta(
            task_id=str(uuid.uuid4()),
            task_type=task_type,
            status=TaskStatus.PENDING,
            payload=payload or {},
        )
        self.store.upsert(task)
        self._queue.append(task)
        return task

    def iter_pending(self) -> Iterator[TaskMeta]:
        self._rebuild_queue()
        while self._queue:
            task = self._queue.popleft()
            yield self.store.get(task.task_id) or task

    def update(
        self,
        task: TaskMeta,
        *,
        status: TaskStatus | None = None,
        progress: int | None = None,
        total: int | None = None,
        checkpoint: Checkpoint | None = None,
        error: str | None = None,
    ) -> TaskMeta:
        update_payload = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        }
        if status:
            update_payload["status"] = status
        if progress is not None:
            update_payload["progress"] = progress
        if total is not None:
            update_payload["total"] = total
        if checkpoint is not None:
            update_payload["checkpoint"] = checkpoint
        if error is not None:
            update_payload["error"] = error
        merged = replace(task, **update_payload)
        self.store.upsert(merged)
        return merged

    @contextlib.contextmanager
    def run_task(
        self,
        task: TaskMeta,
        *,
        total: int | None = None,
    ) -> Iterator[ProgressCallback]:
        """Context manager to run a task with automatic lifecycle tracking."""

        task = self.update(task, status=TaskStatus.IN_PROGRESS, total=total)
        current_task = task

        def callback(progress: int, total_hint: int | None, checkpoint: Checkpoint):
            nonlocal current_task
            current_task = self.update(
                current_task,
                progress=progress,
                total=total_hint if total_hint is not None else current_task.total,
                checkpoint=checkpoint,
            )

        try:
            yield callback
        except KeyboardInterrupt as exc:
            self.update(current_task, status=TaskStatus.PAUSED, error=str(exc))
            raise
        except Exception as exc:  # pylint: disable=broad-except
            self.update(current_task, status=TaskStatus.FAILED, error=str(exc))
            raise TaskExecutionError(str(exc)) from exc
        else:
            final_progress = current_task.progress
            self.update(
                current_task,
                status=TaskStatus.COMPLETED,
                progress=final_progress,
            )

    def resume(self, task_id: str) -> TaskMeta | None:
        task = self.store.get(task_id)
        if task is None:
            return None
        if task.status not in {TaskStatus.PAUSED, TaskStatus.FAILED}:
            return task
        revived = self.update(task, status=TaskStatus.PENDING)
        self._queue.append(revived)
        return revived

    def sync_queue(self) -> None:
        """Refresh the in-memory queue from disk."""
        self._queue = deque(self.store.list())
        self._rebuild_queue()

    def drain(self) -> Iterable[TaskMeta]:
        """Convenience generator to process tasks sequentially."""
        for task in self.iter_pending():
            yield task
