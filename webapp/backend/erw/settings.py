from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_url: str = "sqlite:///var/erw.db"

    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_projects: Annotated[list[str], NoDecode] = []
    jira_webhook_secret: str = ""
    jira_sprint_field: str = "customfield_10020"
    jira_story_points_field: str = "customfield_10016"
    public_base_url: str = ""

    slack_webhook_url: str = ""
    slack_max_per_hour: int = 20

    ollama_url: str = "http://localhost:11434"

    base_duckdb: str = "data/jira.duckdb"
    work_duckdb: str = "var/erw_scoring.duckdb"
    bundles_dir: str = "bundles"
    emb_dir: str = "data"
    stream_dir: str = "var/stream"

    erw_instance: str = "ERW"
    tz: str = "Asia/Ho_Chi_Minh"
    batch_time: str = "06:45"
    digest_time: str = "08:00"
    model_mode: Literal["shadow", "active"] = "shadow"
    llm_model: str = "qwen3:1.7b"
    delay_threshold: float = 0.39
    criticality_top_pct: float = 0.05

    session_secret: str = "erw-secret-key-change-in-production"
    session_cookie_name: str = "erw_session"
    session_max_age_seconds: int = 86400 * 7

    pm_name_by_project: dict[str, str] = {}
    status_category_overrides: dict[str, str] = {}
    web_base_url: str = "http://localhost:8000"

    @field_validator("jira_projects", mode="before")
    @classmethod
    def _split_projects(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
