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
        docs_path = os.path.join(path, "docs.json")
        if os.path.exists(docs_path):
            try:
                with open(docs_path, encoding="utf-8") as f:
                    self.docs = json.load(f)
                _validate_docs(self.docs)
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError("invalid historian state at %s: %s" % (docs_path, exc)) from exc
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

    def find_exact(self, fingerprint, module=None):
        """Find an exact source-row fingerprint; vector similarity is not used."""
        if not fingerprint:
            return None
        for doc in self.docs:
            if doc.get("fingerprint") != fingerprint:
                continue
            if module is None or doc.get("module") == module:
                return doc["log_id"]
        return None

    def query(self, text, k=3, module=None):
        if not self.docs or k <= 0 or not str(text).strip():
            return []
        try:
            X = self.vec.fit_transform(self._texts())
            q = self.vec.transform([(module + " " if module else "") + text])
        except ValueError as exc:
            if "empty vocabulary" in str(exc):
                return []
            raise
        scores = (X @ q.T).toarray().ravel()
        order = np.argsort(-scores)[:k]
        out = []
        for i in order:
            d = self.docs[int(i)]
            if module and d.get("module") != module:
                continue
            out.append({"log_id": d["log_id"], "score": round(float(scores[int(i)]), 4),
                        "module": d.get("module", ""), "text": d.get("text", "")[:160],
                        "metadata": {k: v for k, v in d.items()
                                     if k not in ("log_id", "text")}})
        return out

    def persisted(self):
        return os.path.exists(os.path.join(self.path, "docs.json"))

    def report(self):
        return {"backend": "tfidf", "record_count": len(self.docs),
                "persisted": self.persisted(), "search": "tf-idf lexical similarity"}

    def persist(self):
        os.makedirs(self.path, exist_ok=True)
        target = os.path.join(self.path, "docs.json")
        temporary = target + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(self.docs, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)


class FaissMemory:
    """FAISS IndexFlatIP over hashed char-trigram vectors (deterministic, local)."""

    DIM = 512

    def __init__(self, path):
        import faiss
        self.path = path
        self.docs = []
        self.faiss = faiss
        docs_path = os.path.join(path, "docs.json")
        if os.path.exists(docs_path):
            try:
                with open(docs_path, encoding="utf-8") as f:
                    self.docs = json.load(f)
                _validate_docs(self.docs)
            except (OSError, ValueError, TypeError) as exc:
                raise ValueError("invalid historian state at %s: %s" % (docs_path, exc)) from exc
        self.index = faiss.IndexFlatIP(self.DIM)
        index_path = os.path.join(path, "index.faiss")
        if os.path.exists(index_path) and self.docs:
            try:
                candidate = faiss.read_index(index_path)
                if candidate.ntotal == len(self.docs) and candidate.d == self.DIM:
                    self.index = candidate
                else:
                    self._rebuild()
            except Exception:
                # docs.json is the source of truth; rebuild the derived index.
                self._rebuild()
        elif self.docs:
            self._rebuild()

    def _rebuild(self):
        self.index = self.faiss.IndexFlatIP(self.DIM)
        if self.docs:
            vectors = [self._embed(d.get("module", "") + " " + d.get("text", ""))
                       for d in self.docs]
            self.index.add(np.asarray(vectors, dtype=np.float32))

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

    def find_exact(self, fingerprint, module=None):
        """Find an exact source-row fingerprint; vector similarity is not used."""
        if not fingerprint:
            return None
        for doc in self.docs:
            if doc.get("fingerprint") != fingerprint:
                continue
            if module is None or doc.get("module") == module:
                return doc["log_id"]
        return None

    def query(self, text, k=3, module=None):
        if not self.docs or k <= 0 or not str(text).strip():
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
                        "module": d.get("module", ""), "text": d.get("text", "")[:160],
                        "metadata": {k: v for k, v in d.items()
                                     if k not in ("log_id", "text")}})
            if len(out) >= k:
                break
        return out

    def persisted(self):
        return os.path.exists(os.path.join(self.path, "docs.json"))

    def report(self):
        return {"backend": "faiss", "record_count": len(self.docs),
                "persisted": self.persisted(), "search": "hashed character-trigram similarity"}

    def persist(self):
        os.makedirs(self.path, exist_ok=True)
        docs_tmp = os.path.join(self.path, "docs.json.tmp")
        with open(docs_tmp, "w", encoding="utf-8") as f:
            json.dump(self.docs, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(docs_tmp, os.path.join(self.path, "docs.json"))
        index_tmp = os.path.join(self.path, "index.faiss.tmp")
        self.faiss.write_index(self.index, index_tmp)
        os.replace(index_tmp, os.path.join(self.path, "index.faiss"))


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


def _validate_docs(docs):
    if not isinstance(docs, list):
        raise ValueError("expected a JSON list")
    seen = set()
    for i, doc in enumerate(docs):
        if not isinstance(doc, dict) or not doc.get("log_id"):
            raise ValueError("record %d has no stable log_id" % i)
        if "text" not in doc or not isinstance(doc["text"], str):
            raise ValueError("record %s has no text" % doc["log_id"])
        if doc["log_id"] in seen:
            raise ValueError("duplicate log_id %s" % doc["log_id"])
        seen.add(doc["log_id"])
