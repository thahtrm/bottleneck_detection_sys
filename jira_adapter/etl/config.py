"""Cấu hình cho pipeline ETL MongoDB sang DuckDB."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ETLConfig:
    mongo_host: str = "127.0.0.1:27017"
    mongo_db: str = "JiraReposAnon"
    duckdb_path: str = "data/jira.duckdb"
    batch_size: int = 15000
    preview_len: int = 200
    overwrite: bool = False
    include_comments: bool = True

    @property
    def duckdb_file(self) -> Path:
        return Path(self.duckdb_path)
