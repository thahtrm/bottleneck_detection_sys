"""Bộ trích xuất dữ liệu (Extractor) streaming từ MongoDB theo batch."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def _bson_to_plain(obj: Any) -> Any:
    """Chuyển đổi ObjectId / datetime / bytes thành dạng Python tiêu chuẩn."""
    if isinstance(obj, dict):
        return {k: _bson_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_bson_to_plain(v) for v in obj]
    try:
        from bson import ObjectId
        if isinstance(obj, ObjectId):
            return str(obj)
    except ImportError:
        pass
    if isinstance(obj, bytes):
        return obj.decode("utf-8", "replace")
    return obj


class MongoStreamExtractor:
    def __init__(self, host: str = "127.0.0.1:27017", db_name: str = "JiraReposAnon") -> None:
        self.host = host
        self.db_name = db_name
        self._client = None
        self._db = None

    def connect(self):
        if self._db is None:
            import pymongo
            self._client = pymongo.MongoClient(self.host, serverSelectionTimeoutMS=5000)
            self._db = self._client[self.db_name]
        return self._db

    def ping(self) -> bool:
        db = self.connect()
        res = db.client.admin.command("ping")
        return bool(res.get("ok"))

    def list_instances(self) -> list[dict[str, Any]]:
        db = self.connect()
        out = []
        for name in db.list_collection_names():
            if name.startswith("system."):
                continue
            try:
                n = db[name].estimated_document_count()
            except Exception:
                n = db[name].count_documents({})
            out.append({"instance": name, "n_issues": n})
        return sorted(out, key=lambda r: r["instance"])

    def count_instance(self, instance: str) -> int:
        db = self.connect()
        try:
            return db[instance].estimated_document_count()
        except Exception:
            return db[instance].count_documents({})

    DEFAULT_PROJECTION = {
        "key": 1,
        "changelog": 1,
        "issueLinks": 1,
        "comments": 1,
        "fields.summary": 1,
        "fields.issuetype": 1,
        "fields.priority": 1,
        "fields.status": 1,
        "fields.resolution": 1,
        "fields.created": 1,
        "fields.updated": 1,
        "fields.resolutiondate": 1,
        "fields.assignee": 1,
        "fields.reporter": 1,
        "fields.issuelinks": 1,
        "fields.issueLinks": 1,
        "fields.comments": 1,
        "fields.project": 1,
    }

    def stream_batches(
        self,
        instance: str,
        batch_size: int = 15000,
        limit: int | None = None,
        use_projection: bool = True,
    ) -> Iterator[list[dict]]:
        """Duyệt cursor và yield từng mảng document theo lô (batch).

        Bộ nhớ tiêu thụ luôn cố định O(batch_size).
        """
        db = self.connect()
        proj = self.DEFAULT_PROJECTION if use_projection else None
        cursor = db[instance].find({}, projection=proj, no_cursor_timeout=True, batch_size=batch_size)
        if limit:
            cursor = cursor.limit(limit)

        chunk: list[dict] = []
        try:
            for raw_doc in cursor:
                chunk.append(_bson_to_plain(raw_doc))
                if len(chunk) >= batch_size:
                    yield chunk
                    chunk = []
            if chunk:
                yield chunk
        finally:
            cursor.close()

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
