"""Policy Knowledge Base: chunk the policy PDF and store it in ChromaDB.

Embeddings:
  - Gemini embeddings (gemini-embedding-001, 768 dims) when LLM_ENABLED=1 and GEMINI_API_KEY is set.
  - Offline hashed bag-of-words otherwise, or if Gemini fails.
  POLICY_EMBEDDINGS=local forces the offline method.

The two methods use separate Chroma collections because their vectors have different sizes.
Both are written at ingest time, so queries can fall back to the offline collection.
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Dict

import fitz  # PyMuPDF

COLLECTION_LOCAL = "policy_kb"
COLLECTION_GEMINI = "policy_kb_gemini"
EMBED_DIM = 512
GEMINI_EMBED_DIM = 768
GEMINI_EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001")

log = logging.getLogger(__name__)


class LocalHashEmbedding:
    """Offline embedding: hashed bag-of-words, L2-normalized.

    Used when Gemini is off or unavailable, and in the offline test suite.
    """

    def __call__(self, input):  # chromadb EmbeddingFunction protocol
        import hashlib
        import math

        vectors = []
        for text in input:
            vec = [0.0] * EMBED_DIM
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                h = int(hashlib.md5(token.encode()).hexdigest(), 16)
                vec[h % EMBED_DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

    def embed_documents(self, input):
        return self(input)

    def embed_query(self, input):
        return self(input)

    @staticmethod
    def name() -> str:
        return "local_hash_embedding"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict):
        return LocalHashEmbedding()


class GeminiEmbedding:
    """Gemini embeddings via the google-genai SDK, reduced to 768 dimensions."""

    def __init__(self, api_key: str, model: str = GEMINI_EMBED_MODEL):
        self.api_key = api_key
        self.model = model

    def __call__(self, input):  # chromadb EmbeddingFunction protocol
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        response = client.models.embed_content(
            model=self.model,
            contents=list(input),
            config=types.EmbedContentConfig(output_dimensionality=GEMINI_EMBED_DIM),
        )
        return [list(e.values) for e in response.embeddings]

    def embed_documents(self, input):
        return self(input)

    def embed_query(self, input):
        return self(input)

    @staticmethod
    def name() -> str:
        return "gemini_embedding"

    def get_config(self) -> dict:
        return {"model": self.model}

    @staticmethod
    def build_from_config(config: dict):
        return GeminiEmbedding(api_key=os.environ.get("GEMINI_API_KEY", ""), model=config.get("model", GEMINI_EMBED_MODEL))


def gemini_active() -> bool:
    """True when Gemini embeddings should be used."""
    if os.environ.get("POLICY_EMBEDDINGS", "").lower() == "local":
        return False
    return os.environ.get("LLM_ENABLED") == "1" and bool(os.environ.get("GEMINI_API_KEY"))


def chunk_policy_text(raw_text: str) -> List[Dict]:
    """Split on numbered policy sections ('1. Coverage Limit. ...')."""
    text = re.sub(r"\s+", " ", raw_text)
    matches = list(re.finditer(r"(?<!\S)(\d)\.\s+([A-Z][A-Za-z ]+?)\.\s", text))
    chunks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end].strip()
        chunks.append({
            "id": f"policy-section-{m.group(1)}",
            "section": int(m.group(1)),
            "title": m.group(2).strip(),
            "text": body,
        })
    return chunks


def read_policy_pdf(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def _upsert(client, name: str, embedder, chunks: List[Dict]) -> None:
    collection = client.get_or_create_collection(name, embedding_function=embedder)
    collection.upsert(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[{"section": c["section"], "title": c["title"]} for c in chunks],
    )


def ingest(pdf_path: str, persist_dir: str) -> int:
    """Chunk and store the policy PDF. Returns the number of chunks stored."""
    import chromadb

    chunks = chunk_policy_text(read_policy_pdf(pdf_path))
    client = chromadb.PersistentClient(path=persist_dir)
    _upsert(client, COLLECTION_LOCAL, LocalHashEmbedding(), chunks)

    if gemini_active():
        try:
            _upsert(client, COLLECTION_GEMINI, GeminiEmbedding(os.environ["GEMINI_API_KEY"]), chunks)
        except Exception as exc:  # noqa: BLE001 - Gemini problems must not stop ingestion
            log.warning("Gemini policy embeddings failed, offline index is used instead: %s", exc)
    return len(chunks)


def _query_collection(client, name: str, embedder, question: str, k: int) -> List[Dict]:
    collection = client.get_collection(name, embedding_function=embedder)
    res = collection.query(query_texts=[question], n_results=k)
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({"title": meta["title"], "section": meta["section"], "text": doc, "distance": dist})
    return out


def query(question: str, persist_dir: str, k: int = 3) -> List[Dict]:
    import chromadb

    client = chromadb.PersistentClient(path=persist_dir)
    if gemini_active():
        try:
            return _query_collection(
                client, COLLECTION_GEMINI, GeminiEmbedding(os.environ["GEMINI_API_KEY"]), question, k
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the offline index
            log.warning("Gemini policy search failed, using offline index: %s", exc)
    return _query_collection(client, COLLECTION_LOCAL, LocalHashEmbedding(), question, k)
