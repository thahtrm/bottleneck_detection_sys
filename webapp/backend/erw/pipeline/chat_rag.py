from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from erw.db import utcnow
from erw.integrations.llm import call_ollama_embed
from erw.models import ChatRagChunk
from erw.settings import Settings

log = logging.getLogger(__name__)

_HEADING_SPLIT = re.compile(r"(?m)(?=^#{1,3}\s)")


@dataclass(frozen=True)
class RagChunk:
    id: int
    text: str
    source_uri: str
    score: float
    project_key: str | None


def _seed_dir(settings: Settings) -> Path:
    """Resolve seed dir: settings path, backend var/, or repo-root var/rag/seed."""
    configured = Path(settings.rag_seed_dir)
    here = Path(__file__).resolve()
    backend_seed = here.parents[2] / "var" / "rag" / "seed"
    repo_seed = here.parents[4] / "var" / "rag" / "seed" if len(here.parents) >= 5 else None
    for candidate in (configured, backend_seed, repo_seed):
        if candidate is not None and candidate.is_dir():
            return candidate
    return configured


def _index_path(settings: Settings) -> Path:
    return Path(settings.rag_index_path)


def _split_seed_text(text: str) -> list[str]:
    parts = [p.strip() for p in _HEADING_SPLIT.split(text) if p.strip()]
    if parts:
        return parts
    chunks: list[str] = []
    buf: list[str] = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        buf.append(para)
        if sum(len(x) for x in buf) >= 400:
            chunks.append("\n\n".join(buf))
            buf = []
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _iter_seed_files(seed_dir: Path) -> list[Path]:
    if not seed_dir.is_dir():
        return []
    files = sorted(p for p in seed_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"})
    return files


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return vectors / norms


def _load_faiss(path: Path):
    import faiss

    if not path.is_file():
        return None
    return faiss.read_index(str(path))


def _save_faiss(index, path: Path) -> None:
    import faiss

    path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(path))


def embed_texts(texts: list[str], settings: Settings) -> list[list[float]] | None:
    if not texts:
        return []
    if not settings.ollama_url:
        log.warning("RAG embed skipped: ollama_url empty")
        return None
    try:
        return call_ollama_embed(texts, settings.embed_model, settings.ollama_url)
    except Exception:
        log.warning("RAG embed failed for model %s", settings.embed_model, exc_info=True)
        return None


def rebuild_index(session: Session, settings: Settings) -> int:
    """Reindex approved seed files under var/rag/seed into ChatRagChunk + FAISS.

    Embed first; only then replace DB rows + index so a failed embed cannot leave
    orphan chunks without a matching FAISS file.
    """
    import faiss

    seed_dir = _seed_dir(settings)
    files = _iter_seed_files(seed_dir)
    staged: list[tuple[str, str]] = []
    for path in files:
        try:
            rel = str(path.relative_to(seed_dir.parent if seed_dir.name == "seed" else seed_dir))
        except ValueError:
            rel = str(path)
        raw = path.read_text(encoding="utf-8")
        uri = rel.replace("\\", "/")
        for chunk in _split_seed_text(raw):
            staged.append((uri, chunk))
    if not staged:
        session.execute(delete(ChatRagChunk))
        session.flush()
        index_path = _index_path(settings)
        if index_path.is_file():
            index_path.unlink()
        return 0
    texts = [text for _, text in staged]
    vectors = embed_texts(texts, settings)
    if vectors is None or len(vectors) != len(staged):
        log.warning("RAG rebuild aborted: embed failed or size mismatch")
        return 0
    session.execute(delete(ChatRagChunk))
    session.flush()
    rows: list[ChatRagChunk] = []
    now = utcnow()
    for uri, chunk in staged:
        row = ChatRagChunk(
            corpus="seed_help",
            project_key=None,
            source_uri=uri,
            text=chunk,
            embedding_model=settings.embed_model,
            created_at=now,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    arr = _normalize(np.asarray(vectors, dtype=np.float32))
    index = faiss.IndexIDMap(faiss.IndexFlatIP(arr.shape[1]))
    ids = np.asarray([row.id for row in rows], dtype=np.int64)
    index.add_with_ids(arr, ids)
    _save_faiss(index, _index_path(settings))
    return len(rows)


def retrieve(
    session: Session,
    query: str,
    project_key: str,
    settings: Settings,
    *,
    k: int = 4,
    score_threshold: float = 0.25,
) -> list[RagChunk]:
    """Retrieve seed prose only. On embed/index failure return [] (chat tools still run)."""
    if not query.strip():
        return []
    vectors = embed_texts([query.strip()], settings)
    if vectors is None or not vectors:
        return []
    index = _load_faiss(_index_path(settings))
    if index is None or index.ntotal == 0:
        return []
    q = _normalize(np.asarray(vectors, dtype=np.float32))
    top_k = min(k, index.ntotal)
    scores, ids = index.search(q, top_k)
    out: list[RagChunk] = []
    for score, chunk_id in zip(scores[0].tolist(), ids[0].tolist(), strict=False):
        if chunk_id < 0 or score < score_threshold:
            continue
        row = session.get(ChatRagChunk, int(chunk_id))
        if row is None:
            continue
        if row.project_key is not None and row.project_key != project_key:
            continue
        if row.corpus != "seed_help":
            continue
        out.append(
            RagChunk(
                id=row.id,
                text=row.text,
                source_uri=row.source_uri,
                score=float(score),
                project_key=row.project_key,
            )
        )
    return out


def format_rag_for_prompt(chunks: list[RagChunk]) -> str:
    if not chunks:
        return ""
    lines = ["Tài liệu hướng dẫn (RAG seed — không phải số liệu board):"]
    for chunk in chunks:
        lines.append(f"[source: {chunk.source_uri}]\n{chunk.text.strip()}")
    return "\n\n".join(lines)


def citations_from_chunks(chunks: list[RagChunk]) -> list[dict[str, Any]]:
    return [
        {"type": "rag", "id": str(chunk.id), "label": chunk.source_uri, "score": chunk.score}
        for chunk in chunks
    ]
