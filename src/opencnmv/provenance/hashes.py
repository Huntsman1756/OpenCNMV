"""Content hashing and artifact-set identity (G1-B rule).

artifact_set_id = sha256 over the canonical sort of (role, sha256) pairs —
content identity of a served artifact set. It identifies a
variant_version's content state, never the variant itself.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: str | Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def artifact_set_id(artifacts: list[dict]) -> str:
    pairs = sorted([[a["role"], a["sha256"]] for a in artifacts])
    return sha256_bytes(canon(pairs).encode("utf-8"))
