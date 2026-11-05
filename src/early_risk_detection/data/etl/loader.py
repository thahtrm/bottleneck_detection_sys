"""Bộ nạp dữ liệu (Loader) vào DuckDB với cơ chế bulk batch loading sử dụng PyArrow."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

try:
    import pyarrow as pa
except ImportError:
    pa = None


class DuckDBLoader:
    def __init__(self, duckdb_path: str = "data/jira.duckdb") -> None:
        self.duckdb_path = duckdb_path
        Path(self.duckdb_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.duckdb_path)
        # Tối ưu hóa hiệu năng vectorized và RAM cho DuckDB
        try:
            self.con.execute("PRAGMA threads = 16;")
            self.con.execute("PRAGMA preserve_insertion_order = false;")
            self.con.execute("PRAGMA memory_limit = '10GB';")
        except Exception:
            pass

    def init_schema(self, schema_file: str | Path | None = None) -> None:
        """Đọc và thực thi DDL tạo bảng và view (chưa đánh index)."""
        if schema_file is None:
            schema_file = Path(__file__).parent / "schema.sql"
        ddl = Path(schema_file).read_text(encoding="utf-8")
        self.con.execute(ddl)

    def create_indexes(self, index_file: str | Path | None = None) -> None:
        """Tạo các B-Tree indexes sau khi nạp xong toàn bộ dữ liệu (Deferred Indexing)."""
        if index_file is None:
            index_file = Path(__file__).parent / "indexes.sql"
        if Path(index_file).exists():
            ddl = Path(index_file).read_text(encoding="utf-8")
            self.con.execute(ddl)

    def clear_instance(self, instance: str) -> None:
        """Xóa toàn bộ dữ liệu của một instance để ghi đè (overwrite)."""
        self.con.execute("BEGIN TRANSACTION;")
        try:
            self.con.execute("DELETE FROM issues WHERE instance = ?", [instance])
            self.con.execute("DELETE FROM issue_changelogs WHERE instance = ?", [instance])
            self.con.execute("DELETE FROM issue_links WHERE instance = ?", [instance])
            self.con.execute("DELETE FROM issue_comments WHERE instance = ?", [instance])
            self.con.execute("COMMIT;")
        except Exception:
            self.con.execute("ROLLBACK;")
            raise

    def load_batch(self, batch_data: dict[str, list[tuple]]) -> dict[str, int]:
        """Nạp một lô dữ liệu gồm 4 bảng vào DuckDB với tốc độ cao bằng PyArrow."""
        counts = {k: len(v) for k, v in batch_data.items()}
        self.con.execute("BEGIN TRANSACTION;")
        try:
            # 1. Bảng issues
            if batch_data.get("issues"):
                if pa is not None:
                    col_names = [
                        "instance", "issue_key", "project", "summary", "issuetype", "issuetype_theme",
                        "priority_raw", "priority_norm", "status", "resolution", "created_ts",
                        "updated_ts", "resolved_ts", "assignee", "reporter", "num_changelogs",
                        "num_links", "num_comments", "has_block_or_depend"
                    ]
                    cols = list(zip(*batch_data["issues"]))
                    tbl = pa.Table.from_arrays([pa.array(c) for c in cols], names=col_names)
                    self.con.execute("INSERT OR REPLACE INTO issues SELECT * FROM tbl")
                else:
                    self.con.executemany(
                        """
                        INSERT OR REPLACE INTO issues VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        batch_data["issues"],
                    )

            # 2. Bảng issue_changelogs
            if batch_data.get("changelogs"):
                if pa is not None:
                    col_names = [
                        "instance", "issue_key", "change_id", "author", "created_ts",
                        "field", "from_value", "to_value"
                    ]
                    cols = list(zip(*batch_data["changelogs"]))
                    tbl = pa.Table.from_arrays([pa.array(c) for c in cols], names=col_names)
                    self.con.execute("INSERT INTO issue_changelogs SELECT * FROM tbl")
                else:
                    self.con.executemany(
                        "INSERT INTO issue_changelogs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        batch_data["changelogs"],
                    )

            # 3. Bảng issue_links
            if batch_data.get("links"):
                if pa is not None:
                    col_names = [
                        "instance", "source_key", "target_key", "link_type_raw",
                        "link_type_std", "direction", "is_block_or_depend", "approx_ts"
                    ]
                    cols = list(zip(*batch_data["links"]))
                    tbl = pa.Table.from_arrays([pa.array(c) for c in cols], names=col_names)
                    self.con.execute("INSERT INTO issue_links SELECT * FROM tbl")
                else:
                    self.con.executemany(
                        "INSERT INTO issue_links VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        batch_data["links"],
                    )

            # 4. Bảng issue_comments
            if batch_data.get("comments"):
                if pa is not None:
                    col_names = [
                        "instance", "issue_key", "comment_id", "author", "created_ts",
                        "body_len", "body_preview"
                    ]
                    cols = list(zip(*batch_data["comments"]))
                    tbl = pa.Table.from_arrays([pa.array(c) for c in cols], names=col_names)
                    self.con.execute("INSERT INTO issue_comments SELECT * FROM tbl")
                else:
                    self.con.executemany(
                        "INSERT INTO issue_comments VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batch_data["comments"],
                    )

            self.con.execute("COMMIT;")
        except Exception:
            self.con.execute("ROLLBACK;")
            raise

        return counts

    def get_instance_stats(self, instance: str) -> dict[str, Any]:
        """Lấy số lượng bản ghi của instance trong các bảng."""
        n_issues = self.con.execute(
            "SELECT COUNT(*) FROM issues WHERE instance = ?", [instance]
        ).fetchone()[0]
        n_changelogs = self.con.execute(
            "SELECT COUNT(*) FROM issue_changelogs WHERE instance = ?", [instance]
        ).fetchone()[0]
        n_links = self.con.execute(
            "SELECT COUNT(*) FROM issue_links WHERE instance = ?", [instance]
        ).fetchone()[0]
        n_comments = self.con.execute(
            "SELECT COUNT(*) FROM issue_comments WHERE instance = ?", [instance]
        ).fetchone()[0]
        n_events = self.con.execute(
            "SELECT COUNT(*) FROM v_tgn_events WHERE instance = ?", [instance]
        ).fetchone()[0]
        n_bod = self.con.execute(
            "SELECT COUNT(*) FROM issues WHERE instance = ? AND has_block_or_depend = TRUE",
            [instance],
        ).fetchone()[0]

        return {
            "instance": instance,
            "n_issues": n_issues,
            "n_changelogs": n_changelogs,
            "n_links": n_links,
            "n_comments": n_comments,
            "n_tgn_events": n_events,
            "n_issues_with_block_or_depend": n_bod,
        }

    def close(self) -> None:
        self.con.close()
