"""pfdr - DBLP ingestion and DeepSeek-powered querying for academic papers."""

__version__ = "0.1.3"

from .config import Settings
from .models import Paper, TaskMeta, TaskStatus
from .state import IngestionStateStore, SourceIngestionState
from .storage import PaperStore, TaskStore
from .tasks import TaskManager

# Export logger for use in other modules
from loguru import logger as _logger
__all__ = [
    "Settings",
    "Paper",
    "TaskMeta",
    "TaskStatus",
    "IngestionStateStore",
    "SourceIngestionState",
    "PaperStore",
    "TaskStore",
    "TaskManager",
]
