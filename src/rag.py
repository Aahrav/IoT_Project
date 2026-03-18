from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import faiss
import numpy as np
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer


DEFAULT_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=4)
def _get_embedder(embed_model_name: str) -> SentenceTransformer:
    # SentenceTransformer load is expensive; cache to avoid repeated reloads on Streamlit reruns.
    return SentenceTransformer(embed_model_name)


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    source: str
    text: str


def _clean_text(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def chunk_text(text: str, *, doc_id: str, source: str, chunk_size: int = 900, overlap: int = 140) -> list[Chunk]:
    text = _clean_text(text)
    if not text:
        return []

    chunks: list[Chunk] = []
    i = 0
    while i < len(text):
        j = min(len(text), i + chunk_size)
        chunk = text[i:j].strip()
        if chunk:
            chunks.append(Chunk(doc_id=doc_id, source=source, text=chunk))
        i = max(j - overlap, i + 1)
    return chunks


def load_docs_from_dir(docs_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in sorted(docs_dir.glob("**/*")):
        if p.is_dir():
            continue
        ext = p.suffix.lower()
        if ext in {".txt", ".md"}:
            text = p.read_text(encoding="utf-8", errors="ignore")
            chunks.extend(chunk_text(text, doc_id=p.stem, source=str(p)))
        elif ext == ".pdf":
            reader = PdfReader(str(p))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            text = "\n\n".join(pages)
            chunks.extend(chunk_text(text, doc_id=p.stem, source=str(p)))
    return chunks


@dataclass
class RagIndex:
    embed_model_name: str
    dim: int
    faiss_index: faiss.Index
    chunks: list[Chunk]


def build_index(chunks: list[Chunk], *, embed_model_name: str = DEFAULT_EMBED_MODEL) -> RagIndex:
    model = _get_embedder(embed_model_name)
    texts = [c.text for c in chunks]
    if not texts:
        # Create an empty index with the right dimension.
        dim = model.get_sentence_embedding_dimension()
        return RagIndex(embed_model_name=embed_model_name, dim=dim, faiss_index=faiss.IndexFlatIP(dim), chunks=[])

    emb = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    dim = emb.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(emb.astype(np.float32))
    return RagIndex(embed_model_name=embed_model_name, dim=dim, faiss_index=index, chunks=chunks)


def save_index(idx: RagIndex, index_dir: Path) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(idx.faiss_index, str(index_dir / "docs.faiss"))
    meta = {
        "embed_model_name": idx.embed_model_name,
        "dim": idx.dim,
        "chunks": [{"doc_id": c.doc_id, "source": c.source, "text": c.text} for c in idx.chunks],
    }
    (index_dir / "docs.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def load_index(index_dir: Path) -> RagIndex | None:
    faiss_path = index_dir / "docs.faiss"
    meta_path = index_dir / "docs.meta.json"
    if not faiss_path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    chunks = [Chunk(**c) for c in meta["chunks"]]
    index = faiss.read_index(str(faiss_path))
    return RagIndex(
        embed_model_name=meta["embed_model_name"],
        dim=int(meta["dim"]),
        faiss_index=index,
        chunks=chunks,
    )


@dataclass(frozen=True)
class Retrieved:
    score: float
    chunk: Chunk


def retrieve(idx: RagIndex, query: str, *, k: int = 5) -> list[Retrieved]:
    if not idx.chunks:
        return []
    model = _get_embedder(idx.embed_model_name)
    q = model.encode([query], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
    scores, ids = idx.faiss_index.search(q, k)
    out: list[Retrieved] = []
    for score, i in zip(scores[0].tolist(), ids[0].tolist()):
        if i == -1:
            continue
        out.append(Retrieved(score=float(score), chunk=idx.chunks[int(i)]))
    return out


def format_citations(retrieved: Iterable[Retrieved], *, max_chars: int = 1400) -> str:
    parts: list[str] = []
    used = 0
    for i, r in enumerate(retrieved, start=1):
        snippet = r.chunk.text.strip()
        snippet = snippet[:900] + ("…" if len(snippet) > 900 else "")
        block = f"[{i}] source: {r.chunk.source}\n{snippet}\n"
        if used + len(block) > max_chars and parts:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts).strip()

