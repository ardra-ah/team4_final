"""Policy Knowledge Base: chunk the policy PDF and store it in ChromaDB.

Used by the Policy Validation Agent (RAG) in later phases.
"""

import re
from pathlib import Path
from typing import List, Dict

import fitz  # PyMuPDF

COLLECTION = "policy_kb"
EMBED_DIM = 512


class LocalHashEmbedding:
    """Offline embedding: hashed bag-of-words, L2-normalized.

    Used on Day 1 because the sandbox cannot download the default Chroma model.
    Swap for Gemini embeddings once the API key is configured (Phase 2 follow-up).
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


def ingest(pdf_path: str, persist_dir: str) -> int:
    """Chunk and store the policy PDF. Returns the number of chunks stored."""
    import chromadb

    chunks = chunk_policy_text(read_policy_pdf(pdf_path))
    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_or_create_collection(COLLECTION, embedding_function=LocalHashEmbedding())
    collection.upsert(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[{"section": c["section"], "title": c["title"]} for c in chunks],
    )
    return len(chunks)


def query(question: str, persist_dir: str, k: int = 3) -> List[Dict]:
    import chromadb

    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_collection(COLLECTION, embedding_function=LocalHashEmbedding())
    res = collection.query(query_texts=[question], n_results=k)
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append({"title": meta["title"], "section": meta["section"], "text": doc, "distance": dist})
    return out
