"""Service layer abstractions for pfdr commands."""

from .ingestion import (
    FetchOptions,
    FetchSummary,
    IngestionService,
    RemovalOptions,
    RemovalPlan,
    SourceSelectionError,
)
from .configuration import ConfigurationService, ConfigurationSummary
from .search import QueryOptions, QueryService
from .tasks import TaskService
from .enrichment import (
    AbstractEnrichmentService,
    KeywordExtractionService,
    PaperClusteringService,
    PaperEnrichmentService,
    EnrichmentResult,
    get_category_color,
)

__all__ = [
    "AbstractEnrichmentService",
    "ConfigurationService",
    "ConfigurationSummary",
    "EnrichmentResult",
    "FetchOptions",
    "FetchSummary",
    "IngestionService",
    "KeywordExtractionService",
    "PaperClusteringService",
    "PaperEnrichmentService",
    "QueryOptions",
    "QueryService",
    "RemovalOptions",
    "RemovalPlan",
    "SourceSelectionError",
    "TaskService",
    "get_category_color",
]
