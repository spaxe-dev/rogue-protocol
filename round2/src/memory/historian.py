"""Ship Historian: persistent searchable vector memory.

Factory prefers FAISS (dense hash embeddings, no download) when importable,
else TF-IDF + JSON persistence. Same add/query/persist interface either way.
Similarity is evidence, not proof — callers cite IDs + scores only.
"""
import json
import os

import numpy as np


class TfidfMemory:
    def __init__(self, path):
        self.path = path
        self.docs = []
        if os.path.exists(os.path.join(path, "docs.json")):
            self.docs = json.load(open(os.path.join(path, "docs.json")))
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(max_features=5000, ngram_range=(1, 2),
                                   sublinear_tf=True, min_df=1)

    def _texts(self):
        return [(d.get("module", "") + " " + d.get("text", "")) for d in self.docs]

    def add(self, log_id, text, meta):
        if any(d["log_id"] == log_id for d in self.docs):
            return log_id
        self.docs.append({"log_id": log_id, "text": text, **meta})
        self.persist()
        return log_id

    def query(self, text, k=3, module=None):
        if not self.docs:
            return []
        X = self.vec.fit_transform(self._texts())
        q = self.vec.transform([(module + " " if module else "") + text])
        scores = (X @ q.T).toarray().ravel()
        order = np.argsort(-scores)[:k]
        out = []
        for i in order:
            d = self.docs[int(i)]
            if module and d.get("module") != module:
                continue
            out.append({"log_id": d["log_id"], "score": round(float(scores[int(i)]), 4),
                        "module": d.get("module", ""), "text": d.get("text", "")[:160]})
        return out

    def persisted(self):
        return os.path.exists(os.path.join(self.path, "docs.json"))

    def persist(self):
        os.makedirs(self.path, exist_ok=True)
        json.dump(self.docs, open(os.path.join(self.path, "docs.json"), "w"))


class FaissMemory:
    """FAISS IndexFlatIP over hashed char-trigram vectors (deterministic, local)."""

    DIM = 512

    def __init__(self, path):
        import faiss
        self.path = path
        self.docs = []
        self.faiss = faiss
        if os.path.exists(os.path.join(path, "docs.json")):
            self.docs = json.load(open(os.path.join(path, "docs.json")))
        self.index = faiss.IndexFlatIP(self.DIM)
        if os.path.exists(os.path.join(path, "index.faiss")) and self.docs:
            self.index = faiss.read_index(os.path.join(path, "index.faiss"))

    @staticmethod
    def _embed(text):
        import hashlib
        v = np.zeros(FaissMemory.DIM, dtype=np.float32)
        t = text.lower()
        for i in range(len(t) - 2):
            v[int(hashlib.md5(t[i:i + 3].encode()).hexdigest(), 16) % FaissMemory.DIM] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def add(self, log_id, text, meta):
        if any(d["log_id"] == log_id for d in self.docs):
            return log_id
        self.docs.append({"log_id": log_id, "text": text, **meta})
        self.index.add(np.array([self._embed(meta.get("module", "") + " " + text)]))
        self.persist()
        return log_id

    def query(self, text, k=3, module=None):
        if not self.docs:
            return []
        s, ids = self.index.search(
            np.array([self._embed(((module + " ") if module else "") + text)]),
            min(k * 2, len(self.docs)))
        out = []
        for score, i in zip(s[0], ids[0]):
            if i < 0:
                continue
            d = self.docs[int(i)]
            if module and d.get("module") != module:
                continue
            out.append({"log_id": d["log_id"], "score": round(float(score), 4),
                        "module": d.get("module", ""), "text": d.get("text", "")[:160]})
            if len(out) >= k:
                break
        return out

    def persisted(self):
        return os.path.exists(os.path.join(self.path, "docs.json"))

    def persist(self):
        os.makedirs(self.path, exist_ok=True)
        json.dump(self.docs, open(os.path.join(self.path, "docs.json"), "w"))
        self.faiss.write_index(self.index, os.path.join(self.path, "index.faiss"))


def open_memory(path, backend="auto"):
    """backend: faiss | tfidf | auto (faiss if importable). Returns (store, name)."""
    if backend in ("auto", "faiss"):
        try:
            import faiss  # noqa: F401
            return FaissMemory(path), "faiss"
        except Exception:
            if backend == "faiss":
                raise
    return TfidfMemory(path), "tfidf"
