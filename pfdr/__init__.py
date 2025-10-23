"""pfdr - DBLP ingestion and DeepSeek-powered querying for academic papers."""

__version__ = "0.1.1"

from .config import Settings
from .models import Paper, TaskMeta, TaskStatus
from .state import IngestionStateStore, SourceIngestionState
from .storage import PaperStore, TaskStore
from .tasks import TaskManager
