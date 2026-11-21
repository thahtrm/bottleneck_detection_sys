from pathlib import Path

import numpy as np
import pytest

from erw.models import ChatRagChunk
from erw.pipeline import chat_rag
from erw.settings import Settings


@pytest.fixture
def rag_settings(tmp_path, settings) -> Settings:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "help.md").write_text(
        "# Risk levels\n\nHIGH means ưu tiên xem xét ngay.\n\n## Tools\n\nBoard metrics come from tools.\n",
        encoding="utf-8",
    )
    settings.rag_seed_dir = str(seed)
    settings.rag_index_path = str(tmp_path / "faiss.index")
    settings.embed_model = "nomic-embed-text"
    settings.ollama_url = "http://ollama.test"
    return settings


def _content_vec(text: str, dim: int = 16) -> list[float]:
    vec = np.zeros(dim, dtype=np.float32)
    folded = text.casefold()
    if "high" in folded or "mức" in folded or "risk" in folded:
        vec[0] = 1.0
    if "tool" in folded or "board" in folded:
        vec[1] = 1.0
    if float(vec.sum()) == 0:
        vec[2] = 1.0
    return vec.tolist()


def test_retrieve_empty_when_embed_fails(session, rag_settings, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(chat_rag, "call_ollama_embed", boom)
    assert chat_rag.retrieve(session, "mức HIGH", "DEMO", rag_settings) == []


def test_rebuild_and_retrieve(session, rag_settings, monkeypatch):
    monkeypatch.setattr(
        chat_rag,
        "call_ollama_embed",
        lambda texts, model, base_url, client=None: [_content_vec(t) for t in texts],
    )
    n = chat_rag.rebuild_index(session, rag_settings)
    session.commit()
    assert n >= 1
    assert Path(rag_settings.rag_index_path).is_file()
    assert session.query(ChatRagChunk).count() == n
    chunks = chat_rag.retrieve(session, "mức HIGH nghĩa là gì", "DEMO", rag_settings, k=3, score_threshold=0.01)
    assert chunks
    assert any("HIGH" in c.text for c in chunks)
    assert chunks[0].source_uri.endswith("help.md")


def test_rebuild_aborts_without_wiping_chunks_when_embed_fails(session, rag_settings, monkeypatch):
    monkeypatch.setattr(
        chat_rag,
        "call_ollama_embed",
        lambda texts, model, base_url, client=None: [_content_vec(t) for t in texts],
    )
    n = chat_rag.rebuild_index(session, rag_settings)
    session.commit()
    assert n >= 1
    existing = session.query(ChatRagChunk).count()

    def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(chat_rag, "call_ollama_embed", boom)
    assert chat_rag.rebuild_index(session, rag_settings) == 0
    session.commit()
    assert session.query(ChatRagChunk).count() == existing


def test_no_sentence_transformers_import():
    src = Path(chat_rag.__file__).read_text(encoding="utf-8")
    assert "sentence_transformers" not in src
    assert "SentenceTransformer" not in src
