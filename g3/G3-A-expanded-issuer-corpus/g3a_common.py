"""Shared constants/helpers for the G3-A gate scripts."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "_out"
SRC = REPO / "src"

SAMPLE = HERE / "sample.json"
UNIVERSE = HERE / "universe.json"
EXPECTED = HERE / "expected_inventory.json"
LEG_B = HERE / "leg_b_subset.json"
FREEZE_MANIFEST = HERE / "freeze_manifest.json"

EV_A = OUT / "evidence" / "liveA"      # leg A: full-sample capture
EV_B = OUT / "evidence" / "liveB"      # leg B: subset recapture
OBS_A = OUT / "obs_a.json"
OBS_A_REPLAY = OUT / "obs_a_replay.json"
OBS_B = OUT / "obs_b.json"
DS_A = OUT / "ds_a"                    # bootstrapped dataset (leg A)
DS_S1 = OUT / "ds_seed1"               # determinism rebuild 1
DS_S2 = OUT / "ds_seed2"               # determinism rebuild 2
TAX_DIR = REPO / "g0-r/R10-taxonomy-pinning/evidence"

RESULTS = OUT / "results.jsonl"
MIN_DELAY = 2.5


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
