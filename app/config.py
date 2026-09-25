from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIA_LIBRARY_", env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    admin_token: str = "change-me"
    public_base_url: str = "http://localhost:8000"
    max_media_mb: int = 250
    max_html_mb: int = 8
    scan_concurrency: int = 4
    cookie_dir: Path = Path("/data/auth")
    browser_enabled: bool = True
    browser_timeout_ms: int = 20_000
    browser_scrolls: int = 3
    mcp_api_key: str | None = None

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'media-library.sqlite3'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
