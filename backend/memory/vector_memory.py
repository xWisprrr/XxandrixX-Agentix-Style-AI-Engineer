from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> Counter:
    words = re.findall(r"\b\w+\b", text.lower())
    return Counter(words)


def _cosine_similarity(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    intersection = set(a.keys()) & set(b.keys())
    numerator = sum(a[w] * b[w] for w in intersection)
    sum_a = sum(v ** 2 for v in a.values()) ** 0.5
    sum_b = sum(v ** 2 for v in b.values()) ** 0.5
    if not sum_a or not sum_b:
        return 0.0
    return numerator / (sum_a * sum_b)


class VectorMemory:
    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []

    def add(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        entry = {
            "id": len(self._entries),
            "text": text,
            "tokens": _tokenize(text),
            "metadata": metadata or {},
        }
        self._entries.append(entry)
        logger.debug("VectorMemory: added entry id=%d", entry["id"])
        return entry["id"]

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self._entries:
            return []

        query_tokens = _tokenize(query)
        scored = [
            (entry, _cosine_similarity(query_tokens, entry["tokens"]))
            for entry in self._entries
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        return [
            {"text": e["text"], "metadata": e["metadata"], "score": score}
            for e, score in scored[:top_k]
            if score > 0.0
        ]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
