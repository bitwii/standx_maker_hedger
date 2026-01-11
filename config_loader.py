"""
Configuration loader with environment variable support
"""
import json
import os
from typing import Dict, Any
from pathlib import Path
from dotenv import load_dotenv


class Config:
    """Configuration management class"""

    def __init__(self, config_path: str = "config.json", env_path: str = ".env"):
        """
        Initialize configuration loader.

        Args:
            config_path: Path to config.json file
            env_path: Path to .env file
        """
        self.config_path = Path(config_path)
        self.env_path = Path(env_path)

        # Load environment variables
        if self.env_path.exists():
            load_dotenv(self.env_path)

        # Load JSON config
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(self.config_path, 'r') as f:
            self.config = json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get config value by dot-separated key path.

        Args:
            key: Dot-separated key path (e.g., "trading.symbol")
            default: Default value if key not found

        Returns:
            Config value
        """
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def get_env(self, key: str, default: str = None) -> str:
        """
        Get environment variable.

        Args:
            key: Environment variable name
            default: Default value if not found

        Returns:
            Environment variable value
        """
        value = os.getenv(key, default)
        if value is None:
            raise ValueError(f"Required environment variable not set: {key}")
        return value

    def get_solana_private_key(self) -> str:
        """Get Solana private key from environment"""
        return self.get_env("SOLANA_PRIVATE_KEY")

    def get_lighter_private_key(self) -> str:
        """Get Lighter private key from environment"""
        return self.get_env("LIGHTER_PRIVATE_KEY", "")

    def get_max_position_size(self) -> float:
        """Get max position size from env or config"""
        env_value = os.getenv("MAX_POSITION_SIZE")
        if env_value:
            return float(env_value)
        return self.get("risk_management.max_position_size", 1000.0)

    def get_max_daily_loss(self) -> float:
        """Get max daily loss from env or config"""
        env_value = os.getenv("MAX_DAILY_LOSS")
        if env_value:
            return float(env_value)
        return self.get("risk_management.max_daily_loss", 500.0)

    def reload(self):
        """Reload configuration from file"""
        with open(self.config_path, 'r') as f:
            self.config = json.load(f)


# Singleton instance
_config_instance = None


def get_config(config_path: str = "config.json", env_path: str = ".env") -> Config:
    """Get or create config singleton instance"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config(config_path, env_path)
    return _config_instance
