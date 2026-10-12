"""Small deterministic helpers shared by index-free Chapter 2 graph builders/search."""
from __future__ import annotations

import hashlib
import json
import re


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else wire(value).encode()).hexdigest()


def tokens(text):
    """Return lightweight query terms without a fitted vocabulary or persisted index."""
    identifiers = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text or "")
    split = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+", " ".join(identifiers))
    chinese = []
    for value in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        chinese.extend(value[i:i + 2] for i in range(max(1, len(value) - 1)))
    stop = {"a", "an", "the", "of", "to", "and", "in", "for", "is", "on", "with", "as", "from"}
    return [term.casefold() for term in identifiers + split + chinese if term.casefold() not in stop]
