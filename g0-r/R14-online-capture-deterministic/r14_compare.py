# R14 — ONLINE_CAPTURE_DETERMINISTIC (orchestrator + comparator)
#
# Runs r14_capture.py twice in fully isolated subprocesses:
#   RUN A: <runs>/A, empty Arelle cache (TMP redirect), PYTHONHASHSEED=1
#   RUN B: <runs>/B, empty Arelle cache,                 PYTHONHASHSEED=777
# then compares the preregistered logical projections (hash_scope.json).
#
# If source_state_A != source_state_B the pair is INCONCLUSIVE for pipeline
# determinism (the "same source state" precondition failed — e.g. CNMV changed
# between runs); that is reported as source drift, not a pipeline defect.
#
# Negative control: control_projection adds retrieved_at + IPP ?t={GUID};
# its A/B hashes MUST differ, proving the normalizer removes real volatility.

import hashlib, json, os, subprocess, sys
from pathlib import Path

GATE = Path(__file__).resolve().parent
EV = GATE / "evidence"
RUNS = GATE / "_runs"


def canon_sha(p: Path) -> str:
    obj = json.loads(p.read_text(encoding="utf-8"))
    b = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def run_capture(run: str, seed: str) -> Path:
    root = RUNS / run
    tmp = root / "local" / "temp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    p = subprocess.run([sys.executable, str(GATE / "r14_capture.py"),
                        "--root", str(root), "--run", run],
                       env=env, cwd=str(GATE.parents[1]))
    if p.returncode != 0:
        raise SystemExit(f"run {run} failed rc={p.returncode}")
    return root / "out"


def main() -> int:
    EV.mkdir(exist_ok=True)
    only_compare = "--compare-only" in sys.argv
    if not only_compare:
        outA = run_capture("A", "1")
        outB = run_capture("B", "777")
    else:
        outA, outB = RUNS / "A" / "out", RUNS / "B" / "out"

    levels = ["discovery", "artifact_manifest", "taxonomy", "events",
              "facts_index", "source_state", "control_projection"]
    res = {"levels": {}}
    for lv in levels:
        ha, hb = canon_sha(outA / f"{lv}.json"), canon_sha(outB / f"{lv}.json")
        res["levels"][lv] = {"A": ha, "B": hb, "equal": ha == hb}
        mark = "==" if ha == hb else "!="
        print(f"{lv:24s} A {mark} B   {ha[:16]} {hb[:16]}")

    sa = json.loads((outA / "source_state.json").read_text(encoding="utf-8"))
    sb = json.loads((outB / "source_state.json").read_text(encoding="utf-8"))
    res["source_state_equal"] = res["levels"]["source_state"]["equal"]
    res["determinism_levels_equal"] = all(
        res["levels"][k]["equal"]
        for k in ("discovery", "artifact_manifest", "taxonomy", "events",
                  "facts_index"))
    res["negative_control_differs"] = not res["levels"]["control_projection"]["equal"]

    fa = json.loads((outA / "facts_index.json").read_text(encoding="utf-8"))
    res["filings_parsed"] = len(fa)
    res["ctrlA_all_equal"] = all(v.get("ctrlA") for v in fa.values())
    res["ioerr_total"] = sum(v.get("ioerr") or 0 for v in fa.values())

    # cross-gate oracle: R14 run-A fact hashes vs committed R11/R12 evidence
    r12 = {p.stem.split(".")[0]: p for p in
           (REPO := GATE.parents[1]).glob(
               "g0-r/R12-ipp-arelle-parse/evidence/*.facts.jsonl")}
    r11 = {p.stem.split(".")[0]: p for p in
           REPO.glob("g0-r/R11-esef-arelle-parse/evidence/*.facts.jsonl")}
    prev = {}
    for fid, p in {**r11, **r12}.items():
        prev[fid] = hashlib.sha256(p.read_bytes()).hexdigest().upper()
    res["facts_vs_R11_R12"] = {
        fid: {"equal_to_prior_gate":
              prev.get(fid) == fa[fid]["facts_jsonl_sha256"]}
        for fid in sorted(fa)}
    n_same = sum(1 for v in res["facts_vs_R11_R12"].values()
                 if v["equal_to_prior_gate"])
    res["facts_equal_to_prior_gates"] = f"{n_same}/{len(fa)}"

    verdict = (res["source_state_equal"] and res["determinism_levels_equal"]
               and res["negative_control_differs"])
    res["verdict"] = "PASS" if verdict else (
        "INCONCLUSIVE_SOURCE_DRIFT" if not res["source_state_equal"]
        else "FAIL")
    (EV / "r14_results.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    # keep canonical projections of both runs as evidence
    for run, out in (("A", outA), ("B", outB)):
        d = EV / f"run{run}"
        d.mkdir(exist_ok=True)
        for lv in levels + ["fetch_log"]:
            (d / f"{lv}.json").write_bytes((out / f"{lv}.json").read_bytes())
    print(json.dumps({k: v for k, v in res.items() if k != "levels"},
                     indent=2, ensure_ascii=False)[:2500])
    print("verdict:", res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
