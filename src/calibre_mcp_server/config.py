"""
Configuration module for Calibre MCP Server.

This module handles environment configuration, logging setup, and validation
of required settings for the Calibre MCP Server.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv, find_dotenv


class Config:
    """Configuration class for Calibre MCP Server."""

    def __init__(self) -> None:
        """Initialize configuration by loading environment variables."""
        self._load_environment()
        self._validate_configuration()
        self._setup_logging()

    def _load_environment(self) -> None:
        """
        Load environment variables from .env file.

        Prefers .env in the current working directory, falls back to
        .env next to the package file.
        """
        dot_env_path = find_dotenv(usecwd=True)
        if dot_env_path:
            load_dotenv(dot_env_path)
        else:
            # Fallback: .env next to this file's parent directory
            env_path = Path(__file__).parent.parent / '.env'
            load_dotenv(env_path)

    def _validate_configuration(self) -> None:
        """
        Validate required configuration settings.

        Raises
        ------
        ValueError
            If required configuration is missing or invalid.
        """
        if not self.calibre_library_path:
            raise ValueError(
                "CALIBRE_LIBRARY_PATH is not set in the .env file. "
                "Add it to .env."
            )

        if not Path(self.calibre_library_path).exists():
            raise ValueError(
                f"Calibre library path does not exist: "
                f"{self.calibre_library_path}"
            )

        database_path = (
            Path(self.calibre_library_path) / self.database_filename
        )
        if not database_path.exists():
            raise ValueError(
                f"Calibre database not found: {database_path}"
            )

    def _setup_logging(self) -> None:
        """Configure logging based on environment settings."""
        log_level = getattr(logging, self.log_level.upper(), logging.INFO)

        logging.basicConfig(
            level=log_level,
            format=self.log_format,
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    @property
    def calibre_library_path(self) -> str:
        """Get the Calibre library path from environment."""
        return os.getenv("CALIBRE_LIBRARY_PATH", "")

    @property
    def database_filename(self) -> str:
        """Get the database filename (default: metadata.db)."""
        return os.getenv("CALIBRE_DB_FILENAME", "metadata.db")

    @property
    def read_column_label(self) -> str:
        """Lookup label of the bool custom column used for read state."""
        return os.getenv("CALIBRE_READ_COLUMN", "read")

    @property
    def log_level(self) -> str:
        """Get the logging level from environment (default: INFO)."""
        return os.getenv("LOG_LEVEL", "INFO")

    @property
    def log_format(self) -> str:
        """Get the logging format string."""
        return os.getenv(
            "LOG_FORMAT",
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    @property
    def server_name(self) -> str:
        """Get the MCP server name."""
        return os.getenv("MCP_SERVER_NAME", "Calibre MCP Server")

    @property
    def http_host(self) -> str:
        """Get the HTTP host for network serving (default: 0.0.0.0)."""
        return os.getenv("HTTP_HOST", "0.0.0.0")

    @property
    def http_port(self) -> int:
        """Get the HTTP port for network serving (default: 9001)."""
        return int(os.getenv("HTTP_PORT", "9001"))

    @property
    def transport_mode(self) -> str:
        """Get the transport mode (default: stdio)."""
        return os.getenv("TRANSPORT_MODE", "stdio")


# Global configuration instance
config = Config()
