"""Configuration loader with environment variable expansion."""

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml


class ConfigLoader:
    """Load and parse configuration with environment variable expansion."""

    def __init__(self, config_path: str = None):
        """Initialize configuration loader.

        Args:
            config_path: Path to config.yaml (defaults to poc-parquet-aggregator/config/config.yaml)
        """
        if config_path is None:
            # Default to config/config.yaml relative to this file's parent directory
            base_dir = Path(__file__).parent.parent
            config_path = base_dir / "config" / "config.yaml"

        self.config_path = Path(config_path)
        self._config = None

    def load(self) -> Dict[str, Any]:
        """Load configuration from YAML file with environment variable expansion.

        Returns:
            Configuration dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If config file is invalid
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, "r") as f:
            raw_config = yaml.safe_load(f)

        # Expand environment variables recursively
        self._config = self._expand_env_vars(raw_config)
        return self._config

    def _expand_env_vars(self, obj: Any) -> Any:
        """Recursively expand environment variables in configuration.

        Supports:
        - ${VAR_NAME}: Required variable (raises if not set)
        - ${VAR_NAME:-default}: Variable with default value

        Args:
            obj: Configuration object (dict, list, str, etc.)

        Returns:
            Object with environment variables expanded
        """
        if isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        elif isinstance(obj, str):
            return self._expand_string(obj)
        else:
            return obj

    def _expand_string(self, value: str) -> str:
        """Expand environment variables in a string.

        Args:
            value: String possibly containing ${VAR_NAME} or ${VAR_NAME:-default}

        Returns:
            String with environment variables expanded

        Raises:
            ValueError: If required environment variable is not set
        """
        # Pattern: ${VAR_NAME} or ${VAR_NAME:-default}
        pattern = r"\$\{([A-Z_][A-Z0-9_]*)(:-([^}]*))?\}"

        def replacer(match):
            var_name = match.group(1)
            has_default = match.group(2) is not None
            default_value = match.group(3) if has_default else None

            env_value = os.environ.get(var_name)

            if env_value is not None:
                return env_value
            elif has_default:
                return default_value
            else:
                raise ValueError(
                    f"Required environment variable '{var_name}' is not set. " f"Found in configuration value: {value}"
                )

        return re.sub(pattern, replacer, value)

    def get(self, key_path: str, default: Any = None) -> Any:
        """Get configuration value using dot notation.

        Args:
            key_path: Dot-separated path (e.g., 's3.endpoint')
            default: Default value if key doesn't exist

        Returns:
            Configuration value

        Example:
            >>> config = ConfigLoader().load()
            >>> endpoint = config.get('s3.endpoint')
            >>> batch_size = config.get('performance.db_batch_size', 1000)
        """
        if self._config is None:
            self.load()

        keys = key_path.split(".")
        value = self._config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    @property
    def config(self) -> Dict[str, Any]:
        """Get full configuration dictionary.

        Returns:
            Full configuration
        """
        if self._config is None:
            self.load()
        return self._config


# Singleton instance for convenience
_default_loader = None


def get_config(config_path: str = None, reload: bool = False) -> Dict[str, Any]:
    """Get configuration (singleton pattern).

    Args:
        config_path: Path to config.yaml (optional)
        reload: Force reload from file

    Returns:
        Configuration dictionary
    """
    global _default_loader

    if _default_loader is None or reload:
        _default_loader = ConfigLoader(config_path)
        return _default_loader.load()

    return _default_loader.config


def get_value(key_path: str, default: Any = None) -> Any:
    """Get configuration value using dot notation (convenience function).

    Args:
        key_path: Dot-separated path (e.g., 's3.endpoint')
        default: Default value if key doesn't exist

    Returns:
        Configuration value
    """
    global _default_loader

    if _default_loader is None:
        get_config()

    return _default_loader.get(key_path, default)
