from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    canvas_base_url: str = "https://YOUR_SCHOOL.instructure.com"
    canvas_access_token: str = ""
    database_url: str = "sqlite:///./data/uni_reminder.db"
    planner_backend: Literal["rules", "ollama", "api"] = "rules"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"
    sync_interval_minutes: int = 30
    description_max_chars: int = 4000


@lru_cache
def get_settings() -> Settings:
    return Settings()
