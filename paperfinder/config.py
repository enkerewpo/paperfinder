"""Configuration helpers for the paperfinder project."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    data_dir: Path = Path(os.environ.get("PAPERFINDER_DATA_DIR", "data"))
    papers_filename: str = os.environ.get("PAPERFINDER_PAPERS_FILE", "papers.json")
    tasks_filename: str = os.environ.get("PAPERFINDER_TASKS_FILE", "tasks.json")
    deepseek_api_key: str | None = os.environ.get("DEEPSEEK_API_KEY")
    deepseek_api_base: str = os.environ.get(
        "DEEPSEEK_API_BASE", "https://api.deepseek.com"
    )
    deepseek_model: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
    ingestion_state_filename: str = os.environ.get(
        "PAPERFINDER_INGEST_STATE_FILE", "ingestion_state.json"
    )

    def ensure_data_dir(self) -> None:
        """Create the data directory if it does not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def papers_path(self) -> Path:
        return self.data_dir / self.papers_filename

    @property
    def tasks_path(self) -> Path:
        return self.data_dir / self.tasks_filename

    @property
    def ingestion_state_path(self) -> Path:
        return self.data_dir / self.ingestion_state_filename
