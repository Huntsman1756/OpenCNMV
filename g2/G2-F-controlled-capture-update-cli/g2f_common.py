"""Shared constants/helpers for the G2-F gate scripts."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "_out"
EV_A = OUT / "evidence" / "liveA"       # full frozen-corpus capture
EV_B = OUT / "evidence" / "liveB"       # representative recapture
DS = OUT / "dataset"                    # working copy of G2-C runA
G2C_DS = REPO / "g2/G2-C-columnar-dataset-v1/_out/runA/dataset/v1"
TAX_DIR = REPO / "g0-r/R10-taxonomy-pinning/evidence"
OBS_A = OUT / "obsA.json"
OBS_B = OUT / "obsB.json"
OBS_BOOT = OUT / "obs_bootstrap.json"
RESULTS = OUT / "results.jsonl"
MIN_DELAY = 2.0


def jload(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def jwrite(p: Path, obj) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_bytes(json.dumps(
        obj, ensure_ascii=False, sort_keys=True, indent=1
    ).encode("utf-8"))


def record(name: str, **fields) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"name": name, **fields},
                            ensure_ascii=False, sort_keys=True) + "\n")


def dir_hashes(root: Path) -> dict[str, str]:
    from opencnmv.provenance.hashes import sha256_bytes
    return {str(p.relative_to(root)): sha256_bytes(p.read_bytes())
            for p in sorted(Path(root).rglob("*")) if p.is_file()}
