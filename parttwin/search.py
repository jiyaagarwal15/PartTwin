from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

from parttwin.config import SEMANTIC_TOP_K
from parttwin.db import list_parts

TOKEN_RE = re.compile(r"BX-\d+|[a-z0-9]+", re.I)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def part_document(part: dict) -> str:
    bits = [
        part.get("part_number"),
        part.get("name"),
        part.get("family"),
        part.get("function_label"),
        part.get("function_code"),
        part.get("voltage"),
        part.get("connector"),
        part.get("description"),
        part.get("notes"),
        part.get("io_type"),
        part.get("mounting"),
        part.get("ip_rating"),
        part.get("status"),
    ]
    return " ".join(str(b) for b in bits if b)


class TfidfIndex:
    """Local TF-IDF cosine index. No native FAISS/torch dependency required."""

    def __init__(self, parts: list[dict] | None = None):
        self.parts = parts or list_parts()
        self.docs = [part_document(p) for p in self.parts]
        self.tokenized = [tokenize(d) for d in self.docs]
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray | None = None
        self.matrix: np.ndarray | None = None
        self._build()

    def _build(self) -> None:
        df: Counter[str] = Counter()
        for tokens in self.tokenized:
            df.update(set(tokens))
        self.vocab = {t: i for i, t in enumerate(sorted(df))}
        n = len(self.tokenized)
        v = len(self.vocab)
        if n == 0 or v == 0:
            self.idf = np.zeros(0)
            self.matrix = np.zeros((0, 0))
            return
        idf = np.zeros(v, dtype=float)
        for term, idx in self.vocab.items():
            idf[idx] = math.log((1 + n) / (1 + df[term])) + 1.0
        self.idf = idf
        mat = np.zeros((n, v), dtype=float)
        for i, tokens in enumerate(self.tokenized):
            counts = Counter(tokens)
            for term, c in counts.items():
                j = self.vocab[term]
                tf = c / max(len(tokens), 1)
                mat[i, j] = tf * idf[j]
            norm = np.linalg.norm(mat[i])
            if norm:
                mat[i] /= norm
        self.matrix = mat

    def _vector(self, text: str) -> np.ndarray:
        v = len(self.vocab)
        vec = np.zeros(v, dtype=float)
        tokens = tokenize(text)
        if not tokens or v == 0:
            return vec
        counts = Counter(tokens)
        for term, c in counts.items():
            j = self.vocab.get(term)
            if j is None:
                continue
            vec[j] = (c / len(tokens)) * float(self.idf[j])
        norm = np.linalg.norm(vec)
        if norm:
            vec /= norm
        return vec

    def query(self, text: str, k: int = SEMANTIC_TOP_K, exclude: str | None = None) -> list[tuple[dict, float]]:
        if self.matrix is None or self.matrix.size == 0:
            return []
        q = self._vector(text)
        scores = self.matrix @ q
        order = np.argsort(-scores)
        out: list[tuple[dict, float]] = []
        for idx in order:
            part = self.parts[int(idx)]
            if exclude and part["part_number"] == exclude:
                continue
            score = float(scores[int(idx)])
            if score <= 0:
                continue
            out.append((part, score))
            if len(out) >= k:
                break
        return out


_INDEX: TfidfIndex | None = None


def get_index(refresh: bool = False) -> TfidfIndex:
    global _INDEX
    if _INDEX is None or refresh:
        _INDEX = TfidfIndex()
    return _INDEX


def semantic_search(query: str, k: int = SEMANTIC_TOP_K, exclude: str | None = None) -> list[tuple[dict, float]]:
    return get_index().query(query, k=k, exclude=exclude)
