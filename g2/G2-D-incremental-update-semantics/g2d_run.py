"""G2-D runner: executes every scenario under a hard network deny-all.

Usage: python g2d_run.py --seed 17 --tag A
       python g2d_run.py --seed 991 --tag B

For each scenario directory built by g2d_build.py:
  copy S0 -> _out/scen/<X>/run<tag>/ds (the dataset under test)
  load O1 (hash-pinned observation doc), plan delta, persist delta.json
  apply delta -> S1; then replay O1 -> must be NO_CHANGE
Also executes the fail-closed controls (stale base, tampered delta,
corrupted observation hash, injected mid-write failure).
Writes _out/scen/<X>/run<tag>/result.json per scenario plus
_out/controls_<tag>.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

import g2d_common as C  # noqa: E402


def deny_network():
    """Fail-closed: no socket may connect during classify/apply."""
    def _blocked(*a, **k):
        raise RuntimeError("network access attempted during update")
    socket.socket.connect = _blocked          # type: ignore
    socket.create_connection = _blocked       # type: ignore
    socket.getaddrinfo = _blocked             # type: ignore


def block_gate_code():
    """Fail-closed: production modules may not import gate code."""
    import importlib.abc
    import importlib.util

    class _GateCodeBlocker(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if not name.startswith("opencnmv"):
                return None
            try:
                import importlib.machinery
                spec = importlib.machinery.PathFinder.find_spec(
                    name, path, target)
            except Exception:
                return None
            if spec and spec.origin:
                p = str(spec.origin).replace("\\", "/")
                if "/g0-r/" in p or "/g1/" in p or "/g2/" in p:
                    raise ImportError(f"gate-code import blocked: "
                                      f"{name} ({spec.origin})")
            return None

    sys.meta_path.insert(0, _GateCodeBlocker())


def sha_file(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_scenario(scen: Path, tag: str) -> dict:
    from opencnmv.update import apply as uapply
    from opencnmv.update import delta as udelta
    from opencnmv.update import observe as uobs

    spec = C.load_json(scen / "spec.json")
    run = scen / f"run{tag}"
    if run.exists():
        shutil.rmtree(run)
    ds = run / "ds" / "v1"
    shutil.copytree(scen / "S0" / "v1", ds)

    t0 = time.perf_counter()
    obs = uobs.load(scen / "O1.json")
    base_man = uapply.load_manifest(ds)
    base_tables = uapply.load_tables(ds)
    rows_inspected = sum(len(v) for v in base_tables.values())

    delta = udelta.plan(base_tables, obs,
                        base_man["corpus_logical_sha256"])
    (run / "delta.json").write_bytes(udelta.delta_bytes(delta))

    t1 = time.perf_counter()
    res = uapply.apply_delta(ds, delta)
    t2 = time.perf_counter()

    man1 = uapply.load_manifest(ds)
    # mandatory idempotent replay on the resulting state
    obs2 = uobs.load(scen / "O1.json")
    delta2 = udelta.plan(uapply.load_tables(ds), obs2,
                         man1["corpus_logical_sha256"])
    replay_kinds = sorted({t["transition"]
                           for t in delta2["transitions"]})
    replay_rows = sum(len(v) for v in delta2["rows_added"].values()) + \
        sum(len(v) for v in delta2["rows_updated"].values())
    res2 = uapply.apply_delta(ds, delta2)
    t3 = time.perf_counter()

    out = {
        "scenario": spec["scenario"], "tag": tag,
        "s0_corpus_logical_sha256": base_man["corpus_logical_sha256"],
        "s1_corpus_logical_sha256": man1["corpus_logical_sha256"],
        "delta_id": delta["delta_id"],
        "delta_sha256": sha_file(run / "delta.json"),
        "delta_bytes": (run / "delta.json").stat().st_size,
        "transitions": delta["transitions"],
        "unresolved": delta["unresolved"],
        "rows_added": {t: len(r)
                       for t, r in delta["rows_added"].items() if r},
        "rows_updated": {t: len(r)
                         for t, r in delta["rows_updated"].items() if r},
        "result_corpus_predicted":
            delta["result_corpus_logical_sha256"],
        "apply_status": res["status"],
        "replay": {"transitions": replay_kinds,
                   "row_ops": replay_rows,
                   "apply_status": res2["status"],
                   "corpus_after": uapply.load_manifest(ds)[
                       "corpus_logical_sha256"]},
        "stats": {"rows_inspected": rows_inspected,
                  "plan_ms": round((t1 - t0) * 1000, 1),
                  "apply_ms": round((t2 - t1) * 1000, 1),
                  "replay_ms": round((t3 - t2) * 1000, 1)},
    }
    (run / "result.json").write_bytes(json.dumps(
        out, indent=1, ensure_ascii=False).encode("utf-8"))
    return out


def run_controls(tag: str) -> dict:
    """Fail-closed controls against scenario B's artifacts."""
    from opencnmv.update import apply as uapply
    from opencnmv.update import delta as udelta
    from opencnmv.update import observe as uobs

    out: dict[str, dict] = {}
    scen = C.OUT / "scen" / "B"
    base = scen / f"run{tag}" / "ds" / "v1"   # already at S1
    delta = json.loads((scen / f"run{tag}" / "delta.json")
                       .read_text(encoding="utf-8"))

    # stale base: delta was planned vs S0, dataset is now S1
    try:
        uapply.apply_delta(base, delta)
        out["stale_base"] = {"result": "NOT_REJECTED"}
    except uapply.StaleBaseError as e:
        out["stale_base"] = {"result": "StaleBaseError",
                             "detail": str(e)[:200]}

    # tampered delta document: apply to a FRESH S0 so the base check
    # passes and the delta self-hash verification is what must fire
    fresh0 = scen / f"run{tag}" / "ds-tamper" / "v1"
    shutil.copytree(scen / "S0" / "v1", fresh0)
    bad = json.loads(json.dumps(delta))
    bad["result_corpus_logical_sha256"] = "0" * 64
    try:
        uapply.apply_delta(fresh0, bad)
        out["tampered_delta"] = {"result": "NOT_REJECTED"}
    except Exception as e:
        out["tampered_delta"] = {"result": type(e).__name__,
                                 "detail": str(e)[:200]}

    # corrupted observation self-hash
    obs_p = scen / "O1.json"
    obs = json.loads(obs_p.read_text(encoding="utf-8"))
    obs["filings"][0]["filing"]["registro_oficial"] = "tampered"
    try:
        uobs.verify_self_consistency(obs)
        out["corrupt_observation"] = {"result": "NOT_REJECTED"}
    except uobs.ObservationError:
        out["corrupt_observation"] = {"result": "ObservationError"}

    # injected mid-write failure: staging must be cleaned, base intact
    fresh = scen / f"run{tag}" / "ds-fail" / "v1"
    shutil.copytree(scen / "S0" / "v1", fresh)
    man0 = uapply.load_manifest(fresh)
    delta0 = udelta.plan(uapply.load_tables(fresh),
                         uobs.load(scen / "O1.json"),
                         man0["corpus_logical_sha256"])
    before = {p.name: sha_file(p) for p in fresh.glob("*.parquet")}
    for hook in ("before_tables", "during_table:facts", "before_publish"):
        try:
            uapply.apply_delta(fresh, delta0, fail_hook=hook)
            out[f"fail_{hook}"] = {"result": "NO_ERROR"}
        except RuntimeError:
            after = {p.name: sha_file(p)
                     for p in fresh.glob("*.parquet")}
            staged = list(fresh.parent.glob("*.staging-*"))
            ok = (before == after and not staged
                  and uapply.load_manifest(fresh)["corpus_logical_sha256"]
                  == man0["corpus_logical_sha256"])
            out[f"fail_{hook}"] = {
                "result": "RuntimeError",
                "base_intact": before == after,
                "staging_clean": not staged,
                "manifest_intact": ok}
            out[f"fail_{hook}"]["ok"] = ok
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    deny_network()
    block_gate_code()
    results = {}
    for scen in sorted((C.OUT / "scen").iterdir()):
        if not scen.is_dir():
            continue
        print(f"[run{a.tag}] {scen.name}", flush=True)
        results[scen.name] = run_scenario(scen, a.tag)
        r = results[scen.name]
        print(f"    {r['apply_status']:>9} "
              f"{r['s0_corpus_logical_sha256'][:10]} -> "
              f"{r['s1_corpus_logical_sha256'][:10]} "
              f"replay={r['replay']['transitions']}", flush=True)
    controls = run_controls(a.tag)
    (C.OUT / f"controls_{a.tag}.json").write_bytes(json.dumps(
        {"seed": a.seed, "controls": controls}, indent=1).encode())
    (C.OUT / f"run_{a.tag}.json").write_bytes(json.dumps(
        {"seed": a.seed, "scenarios": results},
        indent=1, ensure_ascii=False).encode())
    print("controls:", json.dumps(
        {k: v.get("result") for k, v in controls.items()}))


if __name__ == "__main__":
    main()
