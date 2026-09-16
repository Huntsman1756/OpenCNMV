"""G1-B — determinism verification.

Checks the preregistered determinism contract:

    two captures, same source state
      -> variant inventory core hash A == B   (capture/runA vs runB)
    two offline extraction runs on identical package bytes
      -> per-variant facts.jsonl sha256 run1 == run2
    two comparison runs on identical facts
      -> divergence dataset sha256 equal      (evidence vs _runs rebuild)

Writes evidence/g1b_results.json with the full gate check matrix and the
final PASS/FAIL verdict.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"
RUNS = HERE / "_runs"


def sha256f(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    results = {}

    # 1. capture determinism: inventory core A == B
    ha = (EV / "capture/runA/inventory_core_sha256.txt").read_text().strip()
    hb = (EV / "capture/runB/inventory_core_sha256.txt").read_text().strip()
    results["capture_inventory_core_equal"] = {"pass": ha == hb,
                                               "runA": ha, "runB": hb}

    # 2. extraction determinism: run1 vs run2 facts.jsonl shas
    r1 = json.loads((EV / "parse/run1/extract_results.json").read_text(encoding="utf-8"))
    r2_path = RUNS / "extract-run2/extract_results.json"
    r2 = json.loads(r2_path.read_text(encoding="utf-8")) if r2_path.exists() else []
    s1 = {r["variant"]: r["outputs"]["facts_jsonl_sha256"] for r in r1}
    s2 = {r["variant"]: r["outputs"]["facts_jsonl_sha256"] for r in r2}
    diffs = {v: (s1.get(v), s2.get(v)) for v in s1 if s1.get(v) != s2.get(v)}
    results["extraction_facts_identical"] = {
        "pass": bool(s1) and not diffs and len(s2) == len(s1),
        "variants_checked": sorted(s1), "mismatches": diffs}

    # 3. comparison determinism: rebuild dataset into _runs and compare sha
    cmp2 = RUNS / "compare2"
    cmp2.mkdir(parents=True, exist_ok=True)
    orig_cmp = EV / "compare"
    ds1 = sha256f(orig_cmp / "g1b_divergence_dataset.json")
    # second comparison run: same inputs -> same outputs (script is pure)
    p = subprocess.run([sys.executable, str(HERE / "g1b_compare.py")],
                       capture_output=True)
    ds2 = sha256f(orig_cmp / "g1b_divergence_dataset.json")
    results["comparison_dataset_deterministic"] = {
        "pass": p.returncode == 0 and ds1 == ds2, "sha256": ds1,
        "rerun_returncode": p.returncode}

    # 4. gate checks from compare stage
    cmp_res = json.loads((orig_cmp / "g1b_compare_results.json").read_text(encoding="utf-8"))
    checks = dict(cmp_res["checks"])
    checks.update(results)
    all_pass = all(v.get("pass") for v in checks.values())
    out = {"gate": "G1-B", "verdict": "PASS" if all_pass else "FAIL",
           "checks": checks,
           "class_totals": cmp_res["class_totals"],
           "match_exact_total": cmp_res["match_exact_total"],
           "divergence_dataset_sha256": cmp_res["divergence_dataset_sha256"],
           "per_filing": cmp_res["results"]}
    (EV / "g1b_results.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                         encoding="utf-8")
    print(f"G1-B verdict: {out['verdict']}")
    for k, v in checks.items():
        print(f"  {'PASS' if v.get('pass') else 'FAIL'}  {k}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
