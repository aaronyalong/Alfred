"""Application settings, loaded from environment variables and an optional .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SecretStr masks the value in repr/logs; read it with .get_secret_value().
    anthropic_api_key: SecretStr | None = None
    alfred_model: str = "claude-opus-5-5"
    # Saved vision readings contain course text, so the default lives in git-ignored data/private.
    alfred_cache_dir: Path = Path("data/private/cache")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once."""
    return Settings()
