"""G2-E verifier: evaluates the preregistered E1-E28 acceptance matrix
over the artifacts produced by g2e_build.py + g2e_run.py + g2e_wheel.py
plus the regression verifiers of G2-A/B/C/D.

    python g2e_verify.py              evaluate existing _out artifacts
    python g2e_verify.py --run-all    build + run A + run B + verify

Writes g2e_verify_results.json (gate root, committed). PASS requires
every applicable check to pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import g2e_common as C  # noqa: E402

RESULTS = HERE / "g2e_verify_results.json"


def load_run(tag: str) -> dict[str, dict]:
    p = C.OUT / f"run{tag}" / "results.jsonl"
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        out[r["name"]] = r
    return out


def j(run: dict, name: str):
    return json.loads(run[name]["stdout"])


def main() -> int:
    if "--run-all" in sys.argv:
        for step in (["g2e_build.py"], ["g2e_run.py", "--tag", "A"],
                     ["g2e_run.py", "--tag", "B"]):
            r = subprocess.run([sys.executable, str(HERE / step[0]),
                                *step[1:]], cwd=REPO)
            if r.returncode != 0:
                print(f"{step} failed")
                return 1

    checks: list[dict] = []

    def ck(cid: str, ok: bool, detail: str = ""):
        checks.append({"id": cid, "status": "PASS" if ok else "FAIL",
                       "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {cid}  {detail}")

    run_a = load_run("A")
    run_b = load_run("B")
    hashes = C.jload(C.OUT / "runA" / "dataset_hashes.json")
    wheel = (C.jload(C.OUT / "wheel_smoke.json")
             if (C.OUT / "wheel_smoke.json").exists() else None)

    # E1 installed wheel exposes `opencnmv`
    ck("E1", bool(wheel and wheel["ok"]),
       "wheel smoke all-commands ok" if wheel else "wheel_smoke.json "
       "missing — run g2e_wheel.py")

    # E2 --help / command tree stable
    h = run_a["help"]["stdout"]
    need = ["dataset", "filings", "filing", "history", "facts", "fact",
            "compare", "events", "mappings", "provenance"]
    ck("E2", run_a["help"]["exit"] == 0
       and all(f"\n  {c}" in h or f" {c}" in h.split(
           "{")[0] for c in need) or all(c in h for c in need),
       "help lists the frozen command tree")

    # E3 dataset info matches G2-C manifest
    info = j(run_a, "dataset.info.json")
    ck("E3", info["corpus_logical_sha256"] == C.CORPUS_SHA256
       and info["dataset_version"] == "COLUMNAR_DATASET_V1"
       and info["counts"]["filings"] == 22
       and info["counts"]["facts"] == 45376,
       info["corpus_logical_sha256"][:16])

    # E4 dataset validate passes
    val = j(run_a, "dataset.validate")
    ck("E4", run_a["dataset.validate"]["exit"] == 0
       and val["status"] == "PASS"
       and all(c["status"] == "PASS" for c in val["checks"]),
       f"{len(val['checks'])} checks PASS")

    # E5 filings deterministic + filters
    filings = [json.loads(x) for x in
               run_a["filings.jsonl"]["stdout"].splitlines()]
    iss = j(run_a, "filings.issuer")
    rng = j(run_a, "filings.range")
    ck("E5", len(filings) == 22
       and all(f["family"] == "IPP" for f in rng)
       and all("IBERDROLA" in f["issuer_denomination"] for f in iss)
       and len(iss) == 7,
       f"{len(filings)} filings; IBERDROLA={len(iss)}; "
       f"2025 IPP range={len(rng)}")

    # E6 filing detail preserves canonical graph
    f = j(run_a, "filing.tef.json")["filing"]
    ok6 = (len(f["submission_variants"]) == 2
           and {v["variant_id"] for v in f["submission_variants"]}
           == {f"{C.TEF}#es", f"{C.TEF}#en"}
           and len(f["version_events"]) == 2
           and len(f["view_resolutions"]) == 2
           and f["filing_versions"])
    ck("E6", ok6, "TEF graph: 2 variants, 2 events, view_resolutions")

    # E7 IBE fallback: one submitted variant, no phantom #en
    ibe = j(run_a, "filing.ibe")["filing"]
    cmp_ibe = j(run_a, "compare.ibe24")
    ok7 = (len(ibe["submission_variants"]) == 1
           and ibe["submission_variants"][0]["variant_id"].endswith("#es")
           and any(v["resolution_mode"] == "FALLBACK_TO_ES"
                   for v in ibe["view_resolutions"])
           and cmp_ibe["status"] == "SKIPPED_SINGLE_VARIANT")
    ck("E7", ok7, "IBE: single #es variant, FALLBACK_TO_ES recorded")

    # E8 TEF scoped lifecycle
    h = j(run_a, "history.tef.json")
    vs = {v["variant_id"]: [vv["version_seq"] for vv in v["versions"]]
          for v in h["variants"]}
    e228 = [e for e in h["version_events"]
            if e["event_date"] == "2025-02-28"][0]
    e313 = [e for e in h["version_events"]
            if e["event_date"] == "2025-03-13"][0]
    ok8 = (vs.get(f"{C.TEF}#es") == [1]
           and vs.get(f"{C.TEF}#en") == [1, 2]
           and e313["scope_status"] == "EN_ONLY_REPLACED"
           and [a["variant_id"] for a in e313["affects"]]
           == [f"{C.TEF}#en"]
           and e313["affects"][0]["after_variant_version_id"]
           == f"{C.TEF}#en#v2"
           and e228["scope_status"] == "VARIANT_SCOPE_NOT_OBSERVABLE"
           and all(a["variant_id"] is None for a in e228["affects"]))
    ck("E8", ok8, "TEF: #es v1; #en v1->v2; 13/03 EN-only; 28/02 "
                  "NOT_OBSERVABLE")

    # E9 structural identity + multiplicity preserved
    dup = j(run_a, "fact.dup")
    eq = j(run_a, "facts.concept")
    ok9 = (dup["structural_key_multiplicity"] > 1
           and "#" in dup["fact_id"])
    ck("E9", ok9, f"fact dup multiplicity="
                  f"{dup['structural_key_multiplicity']}")

    # E10 typed dimension round-trip
    ft = j(run_a, "fact.typed")
    td = [d for d in ft["dimensions"] if d["dim_kind"] == "T"]
    ok10 = (td and td[0]["typed_value"] is not None
            and "T:" in json.dumps(
                ft["canonical_record"].get("dimensions", {})))
    ck("E10", ok10, f"typed dims: {len(ft['dimensions'])}")

    # E11 compound unit preserved
    fu = j(run_a, "fact.unit")
    ok11 = (fu["unit_denominator"] ==
            ["http://www.xbrl.org/2003/instance#shares"]
            and fu["unit_numerator"] ==
            ["http://www.xbrl.org/2003/iso4217#EUR"]
            and "/" in (fu["unit"] or ""))
    ck("E11", ok11, f"unit={fu['unit']}")

    # E12 BBVA divergence present and classified
    cb = j(run_a, "compare.bbva24.json")
    divs = [r for r in cb["records"]
            if r["class"] == "DIVERGENT_SUBMISSION_FACT"]
    eq_div = [r for r in divs
              if r["key"]["concept"].endswith("#Equity")
              and r["key"]["period"] == "2023-01-01"]
    ok12 = (cb["status"] == "COMPARED" and len(eq_div) == 1
            and eq_div[0]["es"]["value"] == "98000000"
            and eq_div[0]["en"]["value"] == "-98000000")
    ck("E12", ok12, f"divergent={len(divs)}, equity={len(eq_div)}")

    # E13 language-sensitive text never a divergence
    ok13 = (cb["counts"]["LANGUAGE_SENSITIVE_NOT_COMPARED"] > 0
            and not any(r["class"] == "DIVERGENT_SUBMISSION_FACT"
                        and r["key"].get("concept_type", "")
                        .endswith(("stringItemType", "textBlockItemType",
                                   "normalizedStringItemType",
                                   "tokenItemType", "langItemType"))
                        for r in cb["records"]))
    ck("E13", ok13,
       f"lang_sensitive={cb['counts']['LANGUAGE_SENSITIVE_NOT_COMPARED']}")

    # E14 non-PROVEN mappings never rewrite identity
    mp = j(run_a, "mappings.san24.json")
    bad = [m for m in mp["mappings"]
           if m["verdict"] != "PROVEN_EQUIVALENT"
           and m["rewrites_identity"]]
    amb = j(run_a, "mappings.verdict")
    ck("E14", not bad
       and all(m["verdict"] == "AMBIGUOUS"
               and not m["rewrites_identity"]
               for m in amb["mappings"])
       and mp["counts_by_verdict"].get("PROVEN_EQUIVALENT", 0) > 0,
       f"SAN24 verdicts={mp['counts_by_verdict']}")

    # E15 provenance reaches pinned evidence
    pv = j(run_a, "provenance.fact")
    sa = pv["provenance"][0]["source_artifact"]
    ev_path = sa["evidence_path"]
    ok15 = (sa["sha256"] in sa["artifact_id"]
            and ev_path.startswith("g1/")
            and not Path(ev_path).is_absolute()
            and (REPO / ev_path).is_file()
            and pv["provenance"][0]["context"]["variant_version_id"])
    ck("E15", ok15, f"evidence={ev_path}")

    # E16 deterministic outputs across runs
    diffs = [n for n in run_a if run_a[n]["stdout"] !=
             run_b.get(n, {}).get("stdout")
             or run_a[n]["exit"] != run_b.get(n, {}).get("exit")]
    ck("E16", not diffs, f"{len(run_a)} commands byte-identical"
       if not diffs else f"differ: {diffs[:5]}")

    # E17 exit codes per contract
    e17 = {
        "ok": run_a["dataset.info"]["exit"] == 0,
        "usage": run_a["err.usage"]["exit"] == 2,
        "missing_ds": run_a["err.missing_dataset"]["exit"] == 3,
        "not_found": (run_a["err.unknown_filing"]["exit"] == 4
                      and run_a["err.unknown_fact"]["exit"] == 4),
        "integrity": (run_a["err.corrupt_info"]["exit"] == 5
                      and run_a["err.deleted_table"]["exit"] == 5),
        "unsupported": None}
    # exit 6 exercised by hiding duckdb/pyarrow in-process
    import builtins
    real_import = builtins.__import__

    def no_duckdb(name, *a, **k):
        if name.split(".")[0] in ("duckdb", "pyarrow"):
            raise ImportError("blocked for E17")
        return real_import(name, *a, **k)

    builtins.__import__ = no_duckdb
    try:
        r6 = C.run_cli(["--dataset", str(C.MINIDS), "dataset", "info"])
        e17["unsupported"] = r6["exit"] == 6 and r6["stdout"] == ""
    finally:
        builtins.__import__ = real_import
    ck("E17", all(v is True for v in e17.values()),
       json.dumps(e17))

    # E18 corrupt/deleted fail closed (no data served)
    ok18 = (run_a["err.corrupt_info"]["exit"] == 5
            and run_a["err.corrupt_query"]["exit"] == 5
            and run_a["err.deleted_table"]["exit"] == 5
            and run_a["err.corrupt_info"]["stdout"] == "")
    ck("E18", ok18, "corrupt byte + deleted table both exit 5, "
                    "empty stdout")

    # E19 read-only: zero authoritative bytes modified
    ck("E19", hashes["identical"] and not hashes["network_attempts"],
       f"{len(hashes['before'])} files identical before/after")

    # E20 zero network under deny-all (the whole corpus ran patched)
    ck("E20", hashes["network_attempts"] == [],
       f"attempts={hashes['network_attempts']}")

    # E21 wheel smoke (this machine, Windows)
    ck("E21", bool(wheel and wheel["ok"]),
       f"{len(wheel['results'])} installed-wheel commands"
       if wheel else "not run")

    # E22 wheel smoke wired into CI for Linux+Windows
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    ck("E22", "opencnmv" in ci and "g2e_build" in ci
       and "windows-latest" in ci and "ubuntu-latest" in ci,
       "CI runs wheel smoke on both OS")

    # E23-E26 gate regressions: re-run each verifier fresh
    regressions = {
        "E23": ("g2/G2-A-durable-canonical-core/g2a_verify.py", "PASS"),
        "E24": ("g2/G2-B-frozen-corpus-rebuild/g2b_verify.py", "PASS"),
        "E25": ("g2/G2-C-columnar-dataset-v1/g2c_verify.py", "PASS"),
        "E26": ("g2/G2-D-incremental-update-semantics/g2d_verify.py",
                "PASS"),
    }
    for cid, (script, want) in regressions.items():
        p = REPO / script
        if not p.exists():
            ck(cid, False, f"{script} missing")
            continue
        r = subprocess.run([sys.executable, str(p)], cwd=REPO,
                           capture_output=True, text=True,
                           timeout=3600)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:]
        ck(cid, r.returncode == 0 and want in (r.stdout + r.stderr),
           tail[0][:110] if tail else f"exit={r.returncode}")

    # E27 dataset compare reproduces G1-C mapped counts exactly
    g1c_dir = (REPO / "g1" / "G1-C-extension-variant-identity" /
               "evidence" / "compare_mapped")
    ok27 = True
    detail27 = []
    for name, fid in C.DUALS.items():
        want_counts: dict[str, int] = {}
        for line in (g1c_dir / f"{name}.comparison.jsonl").read_text(
                encoding="utf-8").splitlines():
            cls = json.loads(line)["class"]
            want_counts[cls] = want_counts.get(cls, 0) + 1
        got = j(run_a, {
            "BBVA-FY2024": "compare.bbva24.json",
            "BBVA-FY2025": "compare.bbva25",
            "SAN-FY2024": "compare.san24",
            "SAN-FY2025": "compare.san25"}[name])["counts"]
        for cls, n in want_counts.items():
            if got.get(cls, 0) != n:
                ok27 = False
                detail27.append(f"{name}:{cls} want {n} got "
                                f"{got.get(cls, 0)}")
    ck("E27", ok27, "G1-C mapped counts reproduced on all 4 dual filings"
       if ok27 else "; ".join(detail27))

    # E28 IPP H2: CURRENT_HALF vs YTD-style contexts sharing period_end
    # stay separately observable (distinct dim members, distinct rows)
    h2 = [json.loads(x) for x in
          run_a["facts.h2dims"]["stdout"].splitlines()]
    members = {d["member_qname"] for r in h2 for d in r["dimensions"]
               if d["member_qname"]}
    ok28 = (len(h2) > 1
            and any("Actual" in (m or "") for m in members)
            and len({r["fact_id"] for r in h2}) == len(h2))
    ck("E28", ok28, f"H2 dim members observed: {len(members)} distinct")

    # E29 committed goldens reproduce runA stdout exactly
    GOLD = {
        "help.txt": ("help", None),
        "dataset_info.json": ("dataset.info.json", None),
        "dataset_validate.json": ("dataset.validate", None),
        "filings.jsonl": ("filings.jsonl", None),
        "filing_ibe.json": ("filing.ibe", None),
        "history_tef.json": ("history.tef.json", None),
        "compare_ibe_fallback.json": ("compare.ibe24", None),
        "fact_typed_dim.json": ("fact.typed", None),
        "fact_compound_unit.json": ("fact.unit", None),
        "fact_multiplicity.json": ("fact.dup", None),
        "provenance_fact.json": ("provenance.fact", None),
        "compare_bbva_fy2024_divergent.json": (
            "compare.bbva24.json",
            lambda d: {**d, "records": [r for r in d["records"] if r[
                "class"] == "DIVERGENT_SUBMISSION_FACT"],
                "records_note": "filtered to DIVERGENT_SUBMISSION_FACT "
                                "for compactness"}),
        "mappings_san_fy2024.json": (
            "mappings.san24.json",
            lambda d: {"filing_id": d["filing_id"], "rule": d["rule"],
                       "counts_by_verdict": d["counts_by_verdict"],
                       "mappings_note": "one representative row per "
                                        "verdict (full list via --json)",
                       "mappings": [next(m for m in d["mappings"]
                                         if m["verdict"] == v)
                                    for v in sorted(
                                        {m["verdict"] for m in
                                         d["mappings"]})]}),
    }
    bad_gold = []
    for fname, (name, proj) in GOLD.items():
        gp = C.GOLDEN / fname
        if not gp.is_file():
            bad_gold.append(f"{fname}: missing")
            continue
        raw = run_a[name]["stdout"]
        if proj:
            raw = json.dumps(proj(json.loads(raw)), indent=1,
                             ensure_ascii=False, sort_keys=True) + "\n"
        if gp.read_text(encoding="utf-8") != raw:
            bad_gold.append(f"{fname}: stale")
    ck("E29", not bad_gold,
       "13 goldens reproduce runA" if not bad_gold else
       "; ".join(bad_gold))

    npass = sum(1 for c in checks if c["status"] == "PASS")
    verdict = "PASS" if npass == len(checks) else "FAIL"
    C.jdump({"gate": "G2-E-public-readonly-cli", "verdict": verdict,
             "checks": checks, "passed": npass, "total": len(checks)},
            RESULTS)
    print(f"\nG2-E: {verdict} ({npass}/{len(checks)})")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
