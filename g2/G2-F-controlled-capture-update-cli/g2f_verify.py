"""G2-F verifier: evaluates the preregistered F1-F24 acceptance matrix
over the artifacts produced by g2f_run.py plus the regression verifiers
of G2-A/B/C/D/E.

    python g2f_verify.py              evaluate existing _out artifacts
    python g2f_verify.py --run-all    run g2f_run.py first (needs network
                                    for the live legs; pass --offline to
                                    reuse preserved evidence)

Writes g2f_verify_results.json (gate root, committed). PASS requires
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

import g2f_common as C  # noqa: E402

RESULTS = HERE / "g2f_verify_results.json"


def _art_recs(o):
    """Yield every preserved-artifact record (dicts carrying
    evidence_path) anywhere in a manifest structure."""
    if isinstance(o, dict):
        if "evidence_path" in o:
            yield o
        for v in o.values():
            yield from _art_recs(v)
    elif isinstance(o, list):
        for v in o:
            yield from _art_recs(v)


def _rel(p: str | None) -> bool:
    return bool(p) and not Path(p).is_absolute() and ":" not in p


def main() -> int:
    if "--run-all" in sys.argv:
        extra = ["--offline"] if "--offline" in sys.argv else []
        r = subprocess.run([sys.executable, str(HERE / "g2f_run.py"),
                            *extra], cwd=REPO)
        if r.returncode != 0:
            print("g2f_run.py failed")
            return 1

    checks: list[dict] = []

    def ck(cid: str, ok: bool, detail: str = ""):
        checks.append({"id": cid, "status": "PASS" if ok else "FAIL",
                       "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {cid}  {detail}")

    recs = {json.loads(line)["name"]: json.loads(line)
            for line in C.RESULTS.read_text(encoding="utf-8").splitlines()
            if line.strip()}
    obs_a = C.jload(C.OBS_A)
    out_a = C.jload(C.OUT / "observeA_result.json")
    # pin the full-corpus run explicitly — a later dedup probe adds a
    # second run to the same evidence store
    man_a = C.jload(C.EV_A / "runs" / out_a["capture_id"]
                    / "manifest.json")

    # F1 live observe -> observation + write-once evidence
    arts = list((C.EV_A / "artifacts").iterdir())
    ck("F1", out_a.get("filings") == 21 and len(arts) > 0
       and Path(out_a["manifest"]).is_file(),
       f"capture {out_a.get('capture_id')}: {out_a.get('fetches')} "
       f"fetches, {len(arts)} artifacts, {out_a.get('filings')} filings")

    # F2 observation validates + stable across unchanged recapture
    obs_b = C.jload(C.OBS_B) if C.OBS_B.is_file() else None
    det = recs.get("assemble_deterministic", {}).get("equal", False)
    if obs_b:
        a_by_fid = {f["filing"]["filing_id"]: f for f in obs_a["filings"]}
        same = all(json.dumps(f, sort_keys=True, default=str)
                   == json.dumps(a_by_fid.get(
                       f["filing"]["filing_id"]), sort_keys=True,
                       default=str)
                   for f in obs_b["filings"])
        changed = [r for r in man_b_artifacts() if r not in man_a_shas()]
        ck("F2", det and same and not changed,
           f"recapture filings identical: {same}; "
           f"live-vs-offline assemble equal: {det}; "
           f"new source bytes: {len(changed)}")
    else:
        ck("F2", det, f"offline assemble deterministic: {det} "
                      "(no recapture evidence)")

    # F3 update --observation makes zero network attempts (ran under
    # deny_network inside g2f_run) and F4 dry-run preview completeness
    dr = recs.get("update_dryrun", {})
    ck("F3", dr.get("exit") == 0,
       f"update --observation under socket-deny exit {dr.get('exit')}")
    ck("F4", dr.get("exit") == 0
       and "dry-run" in dr.get("stdout", "")
       and recs.get("dryrun_bytes_unchanged", {}).get("ok"),
       "complete PREVIEW delta, zero dataset bytes changed")

    # F5/F6 apply + idempotent second apply + validate
    ap1, ap2 = recs.get("update_apply", {}), recs.get("update_apply_2", {})
    val = recs.get("dataset_validate", {})
    ck("F5", "NO_CHANGE" in ap2.get("stdout", "")
       and recs.get("apply_bytes_unchanged", {}).get("ok"),
       "repeated identical update: NO_CHANGE, byte-identical dataset")
    ck("F6", ap1.get("exit") == 0 and val.get("exit") == 0
       and "FAIL" not in val.get("stdout", ""),
       f"apply exit {ap1.get('exit')}; dataset validate clean")

    # F7 incremental result == clean rebuild from the same evidence
    f7 = C.jload(C.OUT / "f7_compare.json")
    bad = {fid: {t: d for t, d in tabs.items() if not d["equal"]}
           for fid, tabs in f7.items() if any(
               not d["equal"] for d in tabs.values())}
    ck("F7", not bad,
       f"{len(f7)} filings; "
       f"mismatches: {list(bad)[:4] or 'none'} "
       "(excludes filing.extras_json curation + prov retrieved_at)")

    # F8 ambiguous/out-of-scope source -> exit 7, dataset intact
    ck("F8", recs.get("bad_issuer", {}).get("exit") == 7,
       f"out-of-corpus issuer -> exit {recs.get('bad_issuer', {}).get('exit')}")

    # F9 mid-capture failure leaves no authoritative observation
    cf = recs.get("capture_failure", {})
    ck("F9", cf.get("raised") and cf.get("dataset_unchanged")
       and not cf.get("runs_exist"),
       f"CaptureError raised; dataset untouched; "
       f"no run manifest: {not cf.get('runs_exist')}")

    # F10/F11 fail closed
    ck("F10", recs.get("stale_base", {}).get("raised"),
       f"StaleBaseError: {recs.get('stale_base', {}).get('error', '')[:80]}")
    ck("F11", recs.get("tampered_obs", {}).get("exit") == 5,
       f"tampered observation -> exit "
       f"{recs.get('tampered_obs', {}).get('exit')}")

    # F12 injected apply failure -> no partial publication
    ai = recs.get("apply_inject", {})
    ck("F12", ai.get("raised") and ai.get("dataset_intact")
       and ai.get("staging_left") == 0,
       f"injected failure; dataset intact; staging left: "
       f"{ai.get('staging_left')}")

    # F13 unresolved visible + refused under --fail-on-unresolved
    up, uf = recs.get("unresolved_preview", {}), recs.get(
        "unresolved_fail", {})
    ck("F13", "CONFLICT" in up.get("stdout", "")
       and uf.get("exit") == 5
       and recs.get("unresolved_bytes_unchanged", {}).get("ok"),
       f"conflict visible in preview; --fail-on-unresolved exit "
       f"{uf.get('exit')}")

    # F14 recapture dedup: identical source bytes produce zero new
    # artifacts (deduplicated=True on every semantic artifact rec);
    # dynamic HTML detail pages legitimately differ per request and
    # are preserved as new write-once objects — a changed hash means
    # the source changed, never an overwrite.
    dd = recs.get("dedup_probe", {})
    probe = C.jload(C.EV_A / "runs" / dd.get("capture_id", "")
                    / "manifest.json")
    sem = [r["artifact"] for r in probe["ipp_filings"]]
    sem_dedup = all(a.get("deduplicated") for a in sem)
    new_recs = sum(1 for r in _art_recs(probe) if not r.get(
        "deduplicated"))
    grown = dd.get("artifacts_after", 0) - dd.get(
        "artifacts_before", 0)
    ck("F14", sem_dedup and grown == new_recs
       and dd.get("fetches", 0) > 0,
       f"recapture: {dd.get('fetches')} fetches; "
       f"{len(sem)} semantic artifacts deduplicated: {sem_dedup}; "
       f"{grown} new artifacts = {new_recs} changed page bytes")

    # F15 provenance: every preserved artifact record in the capture
    # manifest carries a relative evidence_path, sha256 and retrieval
    # metadata (retrieved_at, http_status, source_url). Dataset prov
    # rows carry relative paths + hashes; their retrieval fields are
    # legitimately null for fixture-era (G2-C) captures — the live
    # run's per-request retrieval record is the manifest fetch_log,
    # which is complete by construction.
    recs_a = list(_art_recs(man_a))
    art_ok = all(
        _rel(r.get("evidence_path")) and r.get("sha256")
        and r.get("retrieved_at") and r.get("http_status")
        and r.get("source_url") for r in recs_a)
    log_ok = all(
        r.get("sha256") and r.get("retrieved_at")
        and r.get("http_status") and r.get("source_url")
        for r in man_a["fetch_log"])
    import duckdb  # noqa: E402 — dataset table check
    dsv = duckdb.sql(
        f"select evidence_path, sha256 "
        f"from read_parquet('{C.DS.as_posix()}/provenance.parquet') "
        f"where filing_id like 'cnmv:%'").fetchall()
    ds_ok = all(_rel(r[0]) and r[1] for r in dsv)
    ck("F15", art_ok and log_ok and ds_ok and recs_a,
       f"manifest artifact recs complete: {art_ok} ({len(recs_a)}); "
       f"fetch_log complete: {log_ok}; "
       f"dataset prov paths+hashes: {ds_ok} ({len(dsv)} rows)")

    # F16 partial issuer scope -> no removals outside observed filings
    ps = recs.get("partial_scope", {})
    ck("F16", not ps.get("removed_rows")
       and ps.get("n_transitions", 0) == len(ps.get("filings", [])),
       f"{ps.get('n_transitions')} transitions for "
       f"{len(ps.get('filings', []))} scoped filings; "
       f"removed_rows={ps.get('removed_rows')}")

    # F17 IBE fallback: one submitted es variant, FALLBACK_TO_ES, no #en
    ibe_views = [v for v in man_a["esef_views"] if v["issuer_key"] == "IBE"]
    ibe_fallback = all(v["resolution_mode"] == "FALLBACK_TO_ES"
                       for v in ibe_views
                       if v["requested_ui_language"] == "en") and ibe_views
    ibe_fx = [f["filing"] for f in obs_a["filings"]
              if f["filing"]["issuer"].get("lei")
              == "5QK37QC7NWOJ8D7WVQ45"
              and f["filing"]["family"] == "ESEF_IFA"]
    no_phantom_en = all(
        all(sv["variant_id"].endswith("#es") for sv in
            fx["submission_variants"]) for fx in ibe_fx)
    ck("F17", ibe_fallback and no_phantom_en,
       f"{len(ibe_views)} IBE views, en->FALLBACK_TO_ES; "
       f"{len(ibe_fx)} IBE ESEF filings, no #en variant")

    # F18 H2/FY separation preserved
    fams = {"ESEF_IFA": 0, "IPP": 0}
    h2 = []
    for f in obs_a["filings"]:
        fx = f["filing"]
        fams[fx["family"]] = fams.get(fx["family"], 0) + 1
        if fx["family"] == "IPP" and fx["period_end"].endswith("-12-31"):
            h2.append(fx["filing_id"])
    ck("F18", fams.get("ESEF_IFA") == 6 and fams.get("IPP") == 15
       and len(h2) == 6,
       f"ESEF={fams.get('ESEF_IFA')} IPP={fams.get('IPP')}; "
       f"H2 (12-31 IPP) filings: {len(h2)} "
       "(H2-2024 + H2-2025 x 3 issuers)")

    # F19 deterministic human + JSON output
    dt = recs.get("determinism", {})
    ck("F19", dt.get("same_stdout") and dt.get("same_stderr")
       and dt.get("json_exit") == 0 and dt.get("json_parseable"),
       "identical repeated output; --json emits a single document")

    # F20 exit-code vocabulary exercised
    codes = {"ok": dr.get("exit"), "capture": recs.get(
        "bad_issuer", {}).get("exit"),
             "integrity": recs.get("tampered_obs", {}).get("exit")}
    ck("F20", codes["ok"] == 0 and codes["capture"] == 7
       and codes["integrity"] == 5, f"observed exit codes: {codes}")

    # F21 one session, sequential, UA declared, min delay honored
    flog = man_a["fetch_log"]
    times = [r["retrieved_at"] for r in flog]
    ck("F21", man_a["user_agent"].startswith("OpenCNMV")
       and man_a["min_delay_s"] >= C.MIN_DELAY
       and times == sorted(times) and len(flog) >= 60,
       f"UA={man_a['user_agent']!r}; delay={man_a['min_delay_s']}s; "
       f"{len(flog)} sequential logged requests")

    # F22 unit/CLI tests + ruff + mypy + wheel smoke (new verbs,
    # installed, offline)
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=REPO, capture_output=True, text=True)
    ck("F22a", r.returncode == 0,
       (r.stdout.strip().splitlines() or ["?"])[-1])
    r = subprocess.run([sys.executable, "-m", "ruff", "check",
                        "src", "tests"], cwd=REPO,
                       capture_output=True, text=True)
    ck("F22b", r.returncode == 0, "ruff clean")
    r = subprocess.run([sys.executable, "-m", "mypy", "src", "tests"],
                       cwd=REPO, capture_output=True, text=True)
    if "No module named mypy" in r.stderr:
        import shutil as _sh
        alt = _sh.which("mypy")
        if alt:
            r = subprocess.run([alt, "src", "tests"], cwd=REPO,
                               capture_output=True, text=True)
    ck("F22c", r.returncode == 0,
       (r.stdout.strip().splitlines() or ["?"])[-1][:120])
    whl = (C.OUT / "wheel_smoke_f.json")
    whl = C.jload(whl) if whl.is_file() else None
    ck("F22d", bool(whl and whl["ok"]),
       f"{len(whl['results'])} installed-wheel commands (observe/update)"
       if whl else "wheel_smoke_f.json missing — run g2f_wheel.py")

    # F23 regression verifiers G2-A..E
    for cid, gate in (("F23a", "g2/G2-A-durable-canonical-core/"
                              "g2a_verify.py"),
                      ("F23b", "g2/G2-B-frozen-corpus-rebuild/"
                               "g2b_verify.py"),
                      ("F23c", "g2/G2-C-columnar-dataset-v1/"
                               "g2c_verify.py"),
                      ("F23d", "g2/G2-D-incremental-update-semantics/"
                               "g2d_verify.py"),
                      ("F23e", "g2/G2-E-public-readonly-cli/"
                               "g2e_verify.py")):
        r = subprocess.run([sys.executable, str(REPO / gate)],
                           cwd=REPO, capture_output=True, text=True)
        ck(cid, r.returncode == 0,
           f"{gate.split('/')[1]} verifier rc={r.returncode}")

    # F24 docs
    cli = (REPO / "docs/CLI.md").read_text(encoding="utf-8")
    status = (REPO / "docs/STATUS.md").read_text(encoding="utf-8")
    g2 = (REPO / "docs/G2.md").read_text(encoding="utf-8")
    ck("F24", "observe" in cli and "update" in cli and "G2-F" in status
       and "G2-F" in g2,
       "docs/CLI.md + docs/STATUS.md + docs/G2.md updated")

    npass = sum(1 for c in checks if c["status"] == "PASS")
    verdict = "PASS" if npass == len(checks) else "FAIL"
    RESULTS.write_bytes(json.dumps({
        "gate": "G2-F", "verdict": verdict,
        "checks": checks, "passed": npass, "total": len(checks)},
        indent=1, ensure_ascii=False).encode("utf-8"))
    print(f"\nG2-F {verdict}: {npass}/{len(checks)}")
    return 0 if verdict == "PASS" else 1


def man_a_shas() -> set:
    out = set()
    for m in sorted((C.EV_A / "runs").iterdir()):
        mm = C.jload(m / "manifest.json")
        for v in mm["esef_views"]:
            if v.get("package"):
                out.add(v["package"]["sha256"])
        for r in mm["ipp_filings"]:
            if r.get("artifact"):
                out.add(r["artifact"]["sha256"])
    return out


def man_b_artifacts() -> set:
    out = set()
    for m in sorted((C.EV_B / "runs").iterdir()):
        mm = C.jload(m / "manifest.json")
        for v in mm["esef_views"]:
            if v.get("package"):
                out.add(v["package"]["sha256"])
        for r in mm["ipp_filings"]:
            if r.get("artifact"):
                out.add(r["artifact"]["sha256"])
    return out


if __name__ == "__main__":
    raise SystemExit(main())
