import os
import time

import duckdb
import pytest
from conftest import load_fixture

from erw.ml.duckdb_sync import ensure_work_db, sync_erw_instance, to_dump_shape
from erw.settings import Settings


def _work_settings(tmp_path) -> Settings:
    from early_risk_detection.data.etl.loader import DuckDBLoader

    base = tmp_path / "base.duckdb"
    DuckDBLoader(str(base)).init_schema()
    return Settings(_env_file=None, base_duckdb=str(base), work_duckdb=str(tmp_path / "work.duckdb"))


def _count(path, instance="ERW") -> int:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute("SELECT count(*) FROM issues WHERE instance = ?", [instance]).fetchone()[0]
    finally:
        con.close()


def test_to_dump_shape_moves_comments_and_flattens_adf():
    raw = {
        "key": "DEMO-1",
        "fields": {
            "comment": {"comments": [{"id": "1", "body": "x"}]},
            "description": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}, {"type": "text", "text": "World"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Again"}]},
            ]},
            "issuelinks": [{"id": "9"}],
        },
        "changelog": {"histories": [{"id": "5"}]},
    }
    out = to_dump_shape(raw)
    assert out["fields"]["comments"] == [{"id": "1", "body": "x"}]
    assert "HelloWorld" in out["fields"]["description"] and "Again" in out["fields"]["description"]
    assert isinstance(out["fields"]["description"], str)
    assert out["fields"]["issuelinks"] == [{"id": "9"}]
    assert out["changelog"]["histories"] == [{"id": "5"}]
    assert raw["fields"]["description"]["type"] == "doc"  # input untouched


def test_to_dump_shape_keeps_string_description():
    out = to_dump_shape({"fields": {"description": "plain"}})
    assert out["fields"]["description"] == "plain"


def test_sync_erw_instance_replaces_rows(tmp_path):
    s = _work_settings(tmp_path)
    ensure_work_db(s)
    a = load_fixture("rest_issue_demo1")
    b = {**a, "key": "DEMO-2", "id": "10002"}
    assert sync_erw_instance(s, [a, b]) == 2
    assert _count(s.work_duckdb) == 2
    assert sync_erw_instance(s, [a]) == 1
    assert _count(s.work_duckdb) == 1


def test_ensure_work_db_never_touches_base(tmp_path):
    s = _work_settings(tmp_path)
    os.utime(s.base_duckdb, (1_000_000, 1_000_000))
    before = os.stat(s.base_duckdb)
    time.sleep(0.01)
    p = ensure_work_db(s)
    assert p.exists() and p != __import__("pathlib").Path(s.base_duckdb)
    sync_erw_instance(s, [load_fixture("rest_issue_demo1")])
    assert os.stat(s.base_duckdb).st_mtime == before.st_mtime
    assert _count(s.base_duckdb) == 0


def test_work_db_same_as_base_rejected(tmp_path):
    s = _work_settings(tmp_path)
    same = s.model_copy(update={"work_duckdb": str(tmp_path / "." / "base.duckdb")})
    with pytest.raises(ValueError):
        ensure_work_db(same)
    with pytest.raises(ValueError):
        sync_erw_instance(same, [load_fixture("rest_issue_demo1")])
    assert _count(s.base_duckdb) == 0
