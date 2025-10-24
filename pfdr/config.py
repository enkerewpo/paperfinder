"""Configuration helpers for the pfdr project."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


# Custom YAML representer to maintain key order
def represent_ordered_dict(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())


yaml.add_representer(dict, represent_ordered_dict)


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

    # Generic LLM settings
    llm_provider: str = os.environ.get("PFDR_LLM_PROVIDER", "deepseek")
    llm_api_key: Optional[str] = os.environ.get("PFDR_LLM_API_KEY")
    llm_api_base: Optional[str] = os.environ.get("PFDR_LLM_API_BASE")
    llm_model: Optional[str] = os.environ.get("PFDR_LLM_MODEL")

    # Ingestion targets
    ingestion_targets: List[IngestionTarget] = field(default_factory=list)

    # Web UI settings
    webui_host: str = os.environ.get("PFDR_WEBUI_HOST", "127.0.0.1")
    webui_port: int = int(os.environ.get("PFDR_WEBUI_PORT", "8000"))
    webui_reload: bool = os.environ.get("PFDR_WEBUI_RELOAD", "false").lower() == "true"

    # Config file path
    config_file: Path = Path("config.yaml")

    def __post_init__(self):
        """Load configuration from YAML file after initialization."""
        self.load_from_yaml()
        self._normalize_llm_defaults()

    def load_from_yaml(self) -> None:
        """Load configuration from YAML file."""
        if not self.config_file.exists():
            return

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if not config:
                return

            # Load LLM settings
            if "llm" in config:
                llm_config = config["llm"]
                self.llm_provider = llm_config.get("provider", self.llm_provider)
                self.llm_api_key = llm_config.get("api_key", self.llm_api_key)
                self.llm_api_base = llm_config.get("api_base", self.llm_api_base)
                self.llm_model = llm_config.get("model", self.llm_model)

            # Load ingestion targets
            if "ingestion_targets" in config:
                self.ingestion_targets = []
                for target_data in config["ingestion_targets"]:
                    target = IngestionTarget(
                        name=target_data["name"],
                        url=target_data["url"],
                        enabled=target_data.get("enabled", True),
                    )
                    self.ingestion_targets.append(target)

            # Load Web UI settings
            if "webui" in config:
                webui_config = config["webui"]
                self.webui_host = webui_config.get("host", self.webui_host)
                self.webui_port = webui_config.get("port", self.webui_port)
                self.webui_reload = webui_config.get("reload", self.webui_reload)

        except Exception as e:
            print(f"Warning: Failed to load config from {self.config_file}: {e}")

    def save_to_yaml(self) -> None:
        """Save current configuration to YAML file, preserving user-configured sections."""
        try:
            # Read existing config if it exists
            existing_config = {}
            if self.config_file.exists():
                try:
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        existing_config = yaml.safe_load(f) or {}
                except Exception:
                    # If we can't read the existing config, start fresh
                    existing_config = {}

            # Preserve user-configured sections
            llm_config = existing_config.get("llm", {})
            webui_config = existing_config.get("webui", {})

            # Use user-configured values if they exist in the file, otherwise use current values
            # This ensures that user's manual edits are preserved
            llm_provider = (
                llm_config.get("provider")
                if "provider" in llm_config
                else self.llm_provider
            )
            llm_api_key = (
                llm_config.get("api_key")
                if "api_key" in llm_config and llm_config.get("api_key") is not None
                else self.llm_api_key
            )
            llm_api_base = (
                llm_config.get("api_base")
                if "api_base" in llm_config and llm_config.get("api_base") is not None
                else self.llm_api_base
            )
            llm_model = (
                llm_config.get("model")
                if "model" in llm_config and llm_config.get("model") is not None
                else self.llm_model
            )

            webui_host = (
                webui_config.get("host") if "host" in webui_config else self.webui_host
            )
            webui_port = (
                webui_config.get("port") if "port" in webui_config else self.webui_port
            )
            webui_reload = (
                webui_config.get("reload")
                if "reload" in webui_config
                else self.webui_reload
            )

            with open(self.config_file, "w", encoding="utf-8") as f:
                # Write header comment
                f.write("# pfdr Configuration File\n")
                f.write(
                    "# Synced at "
                    + __import__("datetime")
                    .datetime.now()
                    .strftime("%Y-%m-%d %H:%M:%S")
                    + "\n\n"
                )

                # LLM Configuration section
                f.write("# ============================================\n")
                f.write("# LLM Configuration\n")
                f.write("# ============================================\n")
                f.write("# Configure the Large Language Model for semantic search\n")
                f.write("# Supported providers: deepseek, openai\n")
                f.write("llm:\n")
                f.write(f"  provider: {llm_provider}  # LLM provider to use\n")
                f.write(
                    f"  api_key: {llm_api_key or 'null'}  # API key (set via environment variable PFDR_LLM_API_KEY)\n"
                )
                f.write(f"  api_base: {llm_api_base or 'null'}  # API base URL\n")
                f.write(f"  model: {llm_model or 'null'}  # Model name to use\n\n")

                # Web UI Configuration section
                f.write("# ============================================\n")
                f.write("# Web UI Configuration\n")
                f.write("# ============================================\n")
                f.write("# Configure the web interface settings\n")
                f.write("webui:\n")
                f.write(f"  host: {webui_host}  # Host to bind the web server to\n")
                f.write(f"  port: {webui_port}  # Port to run the web server on\n")
                f.write(
                    f"  reload: {str(webui_reload).lower()}  # Enable auto-reload for development\n\n"
                )

                # Ingestion Targets section (this is what gets synced)
                f.write("# ============================================\n")
                f.write("# Ingestion Targets\n")
                f.write("# ============================================\n")
                f.write("# Configure DBLP API endpoints to fetch papers from\n")
                f.write("# Each target represents a conference or venue\n")
                f.write("# Set 'enabled: false' to temporarily disable a target\n")
                f.write("ingestion_targets:\n")

                for target in self.ingestion_targets:
                    f.write(f"- name: {target.name}\n")
                    f.write(f"  url: {target.url}\n")
                    f.write(f"  enabled: {str(target.enabled).lower()}\n")

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

    def _normalize_llm_defaults(self) -> None:
        """Ensure generic LLM settings are populated consistently."""

        provider = (self.llm_provider or "deepseek").strip() or "deepseek"
        self.llm_provider = provider

        normalized = provider.lower()

        if normalized.startswith("deepseek"):
            if not self.llm_api_base:
                self.llm_api_base = os.environ.get(
                    "DEEPSEEK_API_BASE", "https://api.deepseek.com"
                )
            if not self.llm_model:
                self.llm_model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
            if not self.llm_api_key:
                self.llm_api_key = os.environ.get("DEEPSEEK_API_KEY")
        elif normalized in {"openai", "oai"}:
            if not self.llm_api_base:
                self.llm_api_base = os.environ.get(
                    "OPENAI_API_BASE", "https://api.openai.com/v1"
                )
            if not self.llm_model:
                self.llm_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            if not self.llm_api_key:
                self.llm_api_key = os.environ.get("OPENAI_API_KEY")

    def create_default_config(self) -> None:
        """Create a default config.yaml file if it doesn't exist."""
        if self.config_file.exists():
            return

        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                # Write header comment
                f.write("# pfdr Configuration File\n")
                f.write(
                    "# Initialized at "
                    + __import__("datetime")
                    .datetime.now()
                    .strftime("%Y-%m-%d %H:%M:%S")
                    + "\n\n"
                )

                # LLM Configuration section
                f.write("# ============================================\n")
                f.write("# LLM Configuration\n")
                f.write("# ============================================\n")
                f.write("# Configure the Large Language Model for semantic search\n")
                f.write("# Supported providers: deepseek, openai\n")
                f.write("llm:\n")
                f.write("  provider: deepseek  # LLM provider to use\n")
                f.write(
                    "  api_key: null  # API key (set via environment variable PFDR_LLM_API_KEY)\n"
                )
                f.write("  api_base: https://api.deepseek.com  # API base URL\n")
                f.write("  model: deepseek-chat  # Model name to use\n\n")

                # Web UI Configuration section
                f.write("# ============================================\n")
                f.write("# Web UI Configuration\n")
                f.write("# ============================================\n")
                f.write("# Configure the web interface settings\n")
                f.write("webui:\n")
                f.write("  host: 127.0.0.1  # Host to bind the web server to\n")
                f.write("  port: 8000  # Port to run the web server on\n")
                f.write("  reload: false  # Enable auto-reload for development\n\n")

                # Ingestion Targets section
                f.write("# ============================================\n")
                f.write("# Ingestion Targets\n")
                f.write("# ============================================\n")
                f.write("# Configure DBLP API endpoints to fetch papers from\n")
                f.write("# Each target represents a conference or venue\n")
                f.write("# Set 'enabled: false' to temporarily disable a target\n")
                f.write("ingestion_targets:\n")

                # Default targets
                default_targets = [
                    (
                        "neurips-2023",
                        "https://dblp.org/search/publ/api?q=stream:conf/nips:2023",
                    ),
                    (
                        "icml-2023",
                        "https://dblp.org/search/publ/api?q=stream:conf/icml:2023",
                    ),
                ]

                for name, url in default_targets:
                    f.write(f"- name: {name}\n")
                    f.write(f"  url: {url}\n")
                    f.write(f"  enabled: true\n")

        except Exception as e:
            raise RuntimeError(
                f"Failed to create default config at {self.config_file}: {e}"
            )
