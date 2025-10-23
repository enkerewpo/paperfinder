"""Configuration helpers for the pfdr project."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass(slots=True)
class IngestionTarget:
    """Represents a configured ingestion target."""
    name: str
    url: str
    enabled: bool = True


@dataclass(slots=True)
class Settings:
    """Runtime settings loaded from YAML config file and environment variables."""

    # Data storage paths
    data_dir: Path = Path(os.environ.get("PFDR_DATA_DIR", "data"))
    papers_filename: str = os.environ.get("PFDR_PAPERS_FILE", "papers.json")
    tasks_filename: str = os.environ.get("PFDR_TASKS_FILE", "tasks.json")
    ingestion_state_filename: str = os.environ.get(
        "PFDR_INGEST_STATE_FILE", "ingestion_state.json"
    )

    # DeepSeek API settings
    deepseek_api_key: Optional[str] = None
    deepseek_api_base: str = os.environ.get(
        "DEEPSEEK_API_BASE", "https://api.deepseek.com"
    )
    deepseek_model: str = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    # Ingestion targets
    ingestion_targets: List[IngestionTarget] = field(default_factory=list)

    # Config file path
    config_file: Path = Path("config.yaml")

    def __post_init__(self):
        """Load configuration from YAML file after initialization."""
        self.load_from_yaml()

    def load_from_yaml(self) -> None:
        """Load configuration from YAML file."""
        if not self.config_file.exists():
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config:
                return

            # Load DeepSeek settings
            if 'deepseek' in config:
                deepseek_config = config['deepseek']
                self.deepseek_api_key = deepseek_config.get('api_key') or os.environ.get("DEEPSEEK_API_KEY")
                self.deepseek_api_base = deepseek_config.get('api_base', self.deepseek_api_base)
                self.deepseek_model = deepseek_config.get('model', self.deepseek_model)

            # Load ingestion targets
            if 'ingestion_targets' in config:
                self.ingestion_targets = []
                for target_data in config['ingestion_targets']:
                    target = IngestionTarget(
                        name=target_data['name'],
                        url=target_data['url'],
                        enabled=target_data.get('enabled', True)
                    )
                    self.ingestion_targets.append(target)

        except Exception as e:
            print(f"Warning: Failed to load config from {self.config_file}: {e}")

    def save_to_yaml(self) -> None:
        """Save current configuration to YAML file."""
        config = {
            'deepseek': {
                'api_key': self.deepseek_api_key,
                'api_base': self.deepseek_api_base,
                'model': self.deepseek_model,
            },
            'ingestion_targets': [
                {
                    'name': target.name,
                    'url': target.url,
                    'enabled': target.enabled,
                }
                for target in self.ingestion_targets
            ]
        }

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)
        except Exception as e:
            raise RuntimeError(f"Failed to save config to {self.config_file}: {e}")

    def add_ingestion_target(self, name: str, url: str) -> None:
        """Add a new ingestion target."""
        # Check if target with same name already exists
        for target in self.ingestion_targets:
            if target.name == name:
                target.url = url
                target.enabled = True
                return
        
        # Add new target
        target = IngestionTarget(name=name, url=url)
        self.ingestion_targets.append(target)

    def remove_ingestion_target(self, name: str) -> bool:
        """Remove an ingestion target by name."""
        for i, target in enumerate(self.ingestion_targets):
            if target.name == name:
                del self.ingestion_targets[i]
                return True
        return False

    def get_enabled_targets(self) -> List[IngestionTarget]:
        """Get list of enabled ingestion targets."""
        return [target for target in self.ingestion_targets if target.enabled]

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

    def create_default_config(self) -> None:
        """Create a default config.yaml file if it doesn't exist."""
        if self.config_file.exists():
            return

        default_config = {
            'deepseek': {
                'api_key': 'your-deepseek-api-key-here',
                'api_base': 'https://api.deepseek.com',
                'model': 'deepseek-chat',
            },
            'ingestion_targets': [
                {
                    'name': 'neurips-2023',
                    'url': 'https://dblp.org/search/publ/api?q=stream:conf/nips:2023',
                    'enabled': True,
                },
                {
                    'name': 'icml-2023',
                    'url': 'https://dblp.org/search/publ/api?q=stream:conf/icml:2023',
                    'enabled': True,
                },
            ]
        }

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(default_config, f, default_flow_style=False, allow_unicode=True, indent=2)
        except Exception as e:
            raise RuntimeError(f"Failed to create default config at {self.config_file}: {e}")