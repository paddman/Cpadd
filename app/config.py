from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Cpadd Cherry CFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    database_path: str = "data/cpadd.db"

    qwen_base_url: str = "http://127.0.0.1:8000/v1"
    qwen_model: str = "qwen3.5-9b"
    qwen_api_key: str = "local"
    qwen_temperature: float = 0.2
    qwen_max_tokens: int = 1200
    qwen_timeout_seconds: int = 120

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def ensure_paths(self) -> None:
        Path(self.database_path).expanduser().resolve().parent.mkdir(
            parents=True, exist_ok=True
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_paths()
    return settings
