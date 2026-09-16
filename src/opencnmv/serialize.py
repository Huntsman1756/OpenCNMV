"""Deterministic canonical JSON serialization (LF bytes, indent=1).

All canonical artifacts are serialized through this single function so
byte-exact reproducibility checks are meaningful. Byte writes only —
Path.write_text() would emit CRLF on Windows and break determinism.
"""
from __future__ import annotations

import json
from pathlib import Path


def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8")


def write_canonical(obj, path: str | Path) -> bytes:
    b = canonical_bytes(obj)
    Path(path).write_bytes(b)
    return b
