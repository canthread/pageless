"""Runtime configuration. Every value can be overridden with a PAGELESS_* env var."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAGELESS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pageless:pageless@localhost:5432/pageless"
    seed_on_startup: bool = True

    # Spec constants
    versions_per_route: int = 5
    version_lifetime_hours: float = 5
    grid_columns: int = 12
    retries_per_step: int = 1
    ollama_url: str = "http://localhost:11434"
    ollama_num_parallel: int = 1
    ollama_connect_timeout_s: float = 3
    ollama_read_timeout_s: float = 120  # includes loading the model into VRAM
    # "ollama" composes pages with the active model; "fallback" uses deterministic pages only.
    composer: str = "ollama"

    # Limits
    max_path_chars: int = 200
    max_heading_chars: int = 80
    max_steps: int = 32
    max_output_tokens: int = 2048
    generation_timeout_s: float = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
