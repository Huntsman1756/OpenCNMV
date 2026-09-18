"""Shared constants/helpers for the G2-G gate scripts."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "_out"

# inputs produced by the public G2-F route (evidence + observation are
# legitimate replayable inputs; no gate dataset copy is ever consulted)
G2F = REPO / "g2/G2-F-controlled-capture-update-cli"
EV_A = G2F / "_out/evidence/liveA"          # full-corpus preserved evidence
G2F_OBS_BOOT = G2F / "_out/obs_bootstrap.json"
OBS_IN = OUT / "obs_input.json"             # staged copy of the above
G2C_DS = REPO / "g2/G2-C-columnar-dataset-v1/_out/runA/dataset/v1"
TAX_DIR = REPO / "g0-r/R10-taxonomy-pinning/evidence"

DS_OBS = OUT / "ds_obs"                     # init --observation result
DS_EV = OUT / "ds_ev"                       # init --evidence-dir result
DS_S0 = OUT / "ds_seed0"                    # PYTHONHASHSEED=0 run
DS_S777 = OUT / "ds_seed777"                # PYTHONHASHSEED=777 run
EV_LIVE = OUT / "evidence" / "liveInit"     # init --live evidence output
DS_LIVE = OUT / "ds_live"                   # init --live dataset
DS_LIVE_REPLAY = OUT / "ds_live_replay"     # offline replay of EV_LIVE

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


def run_a_id() -> str:
    """The full-corpus capture run inside liveA (pinned — a later
    dedup probe added a second run to the same store)."""
    return jload(G2F / "_out/observeA_result.json")["capture_id"]
