"""Shared constants/helpers for the G3-A gate scripts."""
from __future__ import annotations

import json
import os
import sys
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


def rec(check: str, ok: bool, detail: str = "") -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"check": check, "ok": bool(ok),
                             "detail": detail},
                            ensure_ascii=False) + "\n")


def run_cli(argv: list[str], *, env_extra: dict | None = None) -> tuple:
    """Run the in-process CLI; returns (exit_code, stdout, stderr)."""
    import contextlib
    import io
    sys.path.insert(0, str(SRC))
    from opencnmv.cli.main import entry
    out, err = io.StringIO(), io.StringIO()
    env = dict(os.environ)
    env.update(env_extra or {})
    code = 0
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        old = dict(os.environ)
        os.environ.update(env_extra or {})
        try:
            code = entry(list(argv))
        except SystemExit as ex:
            code = ex.code if isinstance(ex.code, int) else 0
        finally:
            os.environ.clear()
            os.environ.update(old)
    return code, out.getvalue(), err.getvalue()


def deny_network():
    """Process-level socket deny-all (offline legs)."""
    import socket
    s = socket.socket
    def _deny(*a, **k):
        raise OSError("network denied (offline leg)")
    socket.socket = _deny  # type: ignore[assignment]
    socket.create_connection = _deny  # type: ignore[assignment]
    socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(
        OSError("network denied"))
    return s
