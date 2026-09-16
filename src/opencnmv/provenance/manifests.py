"""Manifest helpers — gate manifests record sha256 for every artifact and
never include the manifest's own hash (self-reference is unsatisfiable)."""
from __future__ import annotations

import hashlib, json
from datetime import datetime, timezone
from pathlib import Path


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def artifact_record(path: Path, root: Path, kind: str, **extra) -> dict:
    body = path.read_bytes()
    rec = {"file": str(path.relative_to(root)).replace("\\", "/"),
           "sha256": sha256(body), "bytes": len(body), "kind": kind}
    rec.update(extra)
    return rec


def new_manifest(gate: str, status: str = "PASS") -> dict:
    return {"gate": gate, "status": status,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "code_commit": None, "inputs": [], "outputs": [],
            "artifacts": [], "sha256": {}, "findings": [],
            "limitations": []}


def finalize(manifest: dict, out_path: Path) -> None:
    manifest["sha256"] = {a["file"]: a["sha256"]
                          for a in manifest["artifacts"]}
    out_path.write_bytes(json.dumps(manifest, indent=1,
                                    ensure_ascii=False).encode("utf-8"))
