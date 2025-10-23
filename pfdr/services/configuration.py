"""Configuration management helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..config import IngestionTarget, Settings


@dataclass(slots=True)
class ConfigurationSummary:
    """Snapshot of key configuration properties for display."""

    config_file: str
    llm_provider: str
    llm_api_key: bool
    llm_api_base: str | None
    llm_model: str | None
    data_dir: str
    ingestion_targets: int


class ConfigurationService:
    """High level configuration operations used by the CLI."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def create_default(self) -> str:
        self.settings.create_default_config()
        return str(self.settings.config_file)

    def summary(self) -> ConfigurationSummary:
        return ConfigurationSummary(
            config_file=str(self.settings.config_file),
            llm_provider=self.settings.llm_provider,
            llm_api_key=bool(self.settings.llm_api_key),
            llm_api_base=self.settings.llm_api_base,
            llm_model=self.settings.llm_model,
            data_dir=str(self.settings.data_dir),
            ingestion_targets=len(self.settings.ingestion_targets),
        )

    def add_target(self, name: str, url: str) -> IngestionTarget:
        self.settings.add_ingestion_target(name, url)
        self.settings.save_to_yaml()
        return self._get_target(name)

    def list_targets(self) -> Iterable[IngestionTarget]:
        return list(self.settings.ingestion_targets)

    def remove_target(self, name: str) -> bool:
        removed = self.settings.remove_ingestion_target(name)
        if removed:
            self.settings.save_to_yaml()
        return removed

    def _get_target(self, name: str) -> IngestionTarget:
        for target in self.settings.ingestion_targets:
            if target.name == name:
                return target
        raise ValueError(f"Target '{name}' not found after addition")
