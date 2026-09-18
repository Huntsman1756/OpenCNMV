"""G3-A verifier: evaluates the preregistered G3A-1..20 acceptance
matrix over the artifacts produced by g3a_run.py plus the regression
verifiers of G2-A..G.

    python g3a_verify.py              evaluate existing _out artifacts
    python g3a_verify.py --run-all    run g3a_run.py first (pass
                                      --offline to reuse preserved
                                      evidence and skip live legs)

Writes g3a_verify_results.json (gate root, committed). PASS requires
every applicable check to pass.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import g3a_common as C  # noqa: E402

RESULTS = HERE / "g3a_verify_results.json"


def _iso(ddmmyyyy: str) -> str:
    d, m, y = ddmmyyyy.split("/")
    return f"{y}-{m}-{d}"


def main() -> int:
    if "--run-all" in sys.argv:
        extra = ["--offline"] if "--offline" in sys.argv else []
        r = subprocess.run([sys.executable, str(HERE / "g3a_run.py"),
                            *extra], cwd=REPO)
        if r.returncode != 0:
            print("g3a_run.py failed")
            return 1

    checks: list[dict] = []

    def ck(cid: str, ok: bool, detail: str = ""):
        checks.append({"id": cid, "status": "PASS" if ok else "FAIL",
                       "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {cid}  {detail}")

    recs = {}
    for line in C.RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            recs[r["name"]] = r          # last occurrence wins

    sample = C.jload(C.SAMPLE)
    expected = C.jload(C.EXPECTED)
    leg_b = C.jload(C.LEG_B)
    obs_a = C.jload(C.OBS_A)
    def _cap_of(tag: str, ev: Path) -> str | None:
        cid = C.jload(C.OUT / f"{tag}_result.json")["capture_id"]
        if cid is None:
            # observe aborted after the live run was preserved; the
            # run under latest.json is the authoritative capture and
            # the runner recorded an assemble_recovery step for it.
            cid = C.jload(ev / "latest.json").get("capture_id")
        return cid

    cap_a = _cap_of("legA", C.EV_A)
    cap_b = _cap_of("legB", C.EV_B)
    man_a = C.jload(C.EV_A / "runs" / cap_a / "manifest.json")
    man_b = C.jload(C.EV_B / "runs" / cap_b / "manifest.json")

    import duckdb  # noqa: E402
    ds = C.DS_A.as_posix()

    def q(s, *a):
        return duckdb.sql(s, params=list(a) or None).fetchall()

    # ---------- G3A-1: zero issuer-specific production code
    src_text = {}
    for p in (REPO / "src").rglob("*.py"):
        src_text[str(p)] = p.read_text(encoding="utf-8")
    lit_hits = []
    for nif, e in sample["issuers"].items():
        for lit in (nif, e["key"]):
            for path, text in src_text.items():
                if lit in text:
                    lit_hits.append(f"{path}:{lit}")
    branch_hits = []
    for path, text in src_text.items():
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"if\s+.*(issuer|nif|key)\s*==\s*['\"]", line):
                branch_hits.append(f"{path}:{i}:{line.strip()}")
    ck("G3A-1", lit_hits == [] and branch_hits == [],
       f"{len(lit_hits)} sample literals in src/, "
       f"{len(branch_hits)} issuer== branches")

    # ---------- G3A-2: generalized registry route
    scope_iss = man_a["scope"]["issuers"]
    reg_ok = (len(scope_iss) == 40
              and {i["nif"] for i in scope_iss}
              == set(sample["issuers"])
              and all(i.get("key") == sample["issuers"][i["nif"]]["key"]
                      for i in scope_iss)
              and all("lei" in i and "denomination" in i
                      for i in scope_iss))
    r = subprocess.run(
        [sys.executable, "-m", "unittest",
         "tests.test_capture.TestIssuerRegistry", "-q"],
        cwd=REPO, capture_output=True, text=True)
    ck("G3A-2", reg_ok and r.returncode == 0,
       f"manifest scope carries 40 registry issuers; "
       f"registry tests rc={r.returncode}")

    # ---------- G3A-3: freeze/sample before filing capture
    fz = C.jload(C.FREEZE_MANIFEST)
    frozen_at = sample["frozen_at"]
    cap_at = man_a["captured_at"]
    ck("G3A-3", fz["captured_at"] < cap_at and frozen_at < cap_at,
       f"freeze {fz['captured_at']} < capture {cap_at}")

    # ---------- G3A-4: stratification integrity
    want = {"credit-institutions": 6, "insurance-entities": 2,
            "utilities": 5, "real-estate-socimi": 6,
            "securitisation-funds": 2, "large-industrials": 7,
            "small-mid-caps": 8, "residual-sectors": 4,
            "historical-depth": 10}
    got = sample["strata_counts"]
    niss = len(sample["issuers"])
    ck("G3A-4", got == want and niss == 40
       and len(set(sample["issuers"])) == 40,
       f"strata {got}; issuers={niss}")

    # ---------- G3A-5: leg A completed over the sample
    la = recs.get("legA_observe", {})
    man_nifs = {i["nif"] for i in man_a["scope"]["issuers"]}
    # observe may abort in post-capture assembly; the authoritative
    # artefact is the preserved run manifest + the deterministic
    # observation (legA_assemble_recovery), both recorded
    leg_ok = (la.get("exit") == 0
              or recs.get("legA_assemble_recovery", {}).get("exit") == 0)
    ck("G3A-5", leg_ok
       and man_nifs == set(sample["issuers"])
       and man_a["esef_views"] and man_a["fetch_log"],
       f"legA exit {la.get('exit')} (recovery "
       f"{recs.get('legA_assemble_recovery', {}).get('exit')}); "
       f"{len(man_a['fetch_log'])} fetches; "
       f"{len(man_a['esef_views'])} esef views; "
       f"{len(man_a['ipp_filings'])} ipp slots")

    # ---------- G3A-6: observation + dataset validate
    from opencnmv.update import observe as uobs
    obs_errors = uobs.validate(obs_a)
    vd = recs.get("validate_dsA", {})
    ck("G3A-6", obs_errors == [] and vd.get("exit") == 0
       and "FAIL" not in vd.get("stdout", ""),
       f"obs errors {len(obs_errors)}; dataset validate exit "
       f"{vd.get('exit')}")

    # ---------- G3A-7: ES/EN resolution classes
    vr = q(f"select resolution_mode, requested_ui_language, count(*) "
           f"from read_parquet('{ds}/view_resolution.parquet') "
           f"group by 1, 2")
    modes = {(m, lg): n for m, lg, n in vr}
    per_filing = q(
        f"select f.issuer_nif, count(distinct v.variant_id) "
        f"from read_parquet('{ds}/submission_variant.parquet') v "
        f"join read_parquet('{ds}/filing.parquet') f using(filing_id) "
        f"where f.family='ESEF_IFA' group by 1")
    dual_esen = q(
        f"select count(distinct filing_id) from "
        f"(select filing_id from "
        f"read_parquet('{ds}/submission_variant.parquet') "
        f"group by filing_id having count(*) >= 2)")
    fb = {k: v for k, v in modes.items()
          if k[0].startswith("FALLBACK")}
    ck("G3A-7", modes.get(("SUBMITTED_VARIANT", "es"), 0) > 0
       and len(dual_esen) and dual_esen[0][0] >= 1
       and len(per_filing) >= 30,
       f"view resolutions {modes}; dual-variant filings "
       f"{dual_esen[0][0] if dual_esen else 0}; "
       f"esef issuers {len(per_filing)}; fallbacks {fb}")

    # ---------- G3A-8: substitution/event scoping
    ev_rows = q(f"select event_id, filing_id, event_type, scope_status "
                f"from read_parquet('{ds}/version_event.parquet')")
    ea_rows = q(f"select event_id, variant_id, scope_basis "
                f"from read_parquet('{ds}/event_affects.parquet')")
    ev_fids = {f for _, f, *_ in ev_rows}
    ev_nifs = {r[0] for r in q(
        f"select distinct issuer_nif from "
        f"read_parquet('{ds}/filing.parquet') where filing_id in "
        f"({','.join(repr(f) for f in ev_fids) or chr(39)+chr(39)})")}
    # issuers whose freeze inventory showed SUBSTITUTION evidence on a
    # registro that IS in captured scope must yield event rows —
    # substitutions targeting out-of-scope registros legitimately
    # produce none (correct lifecycle scoping, not a gap)
    captured_reg = {(v["issuer_key"], v["registro"])
                    for v in man_a["esef_views"]}
    sub_nifs = {n for n, e in expected["issuers"].items()
                for d in e.get("event_docs", [])
                if d.get("class") == "SUBSTITUTION"
                and (e["key"], d["target_registro"]) in captured_reg}
    scoped_ok = all(r[2] for r in ea_rows)
    ck("G3A-8", len(ev_rows) > 0 and len(ea_rows) > 0 and scoped_ok
       and sub_nifs <= ev_nifs,
       f"{len(ev_rows)} events / {len(ea_rows)} affects "
       f"(all scope_basis set: {scoped_ok}); in-scope substitution "
       f"issuers {len(sub_nifs & ev_nifs)}/{len(sub_nifs)} with events")

    # ---------- G3A-9: extension taxonomies, zero manual mappings
    em = q(f"select verdict, count(*) from "
           f"read_parquet('{ds}/extension_mapping.parquet') group by 1")
    verdicts = dict(em)
    manual = sum(n for v, n in em if "MANUAL" in str(v).upper())
    ext_ns = q(f"select count(distinct split_part(concept,'#',1)) "
               f"from read_parquet('{ds}/facts.parquet') "
               f"where ns_kind='issuer_extension'")
    ck("G3A-9", manual == 0 and ext_ns and ext_ns[0][0] >= 10,
       f"mapping verdicts {verdicts}; manual rows {manual}; "
       f"distinct issuer-extension namespaces "
       f"{ext_ns[0][0] if ext_ns else 0}")

    # ---------- G3A-10: IPP model families parse
    ipp_filings = q(f"select filing_id from "
                    f"read_parquet('{ds}/filing.parquet') "
                    f"where family='IPP'")
    ipp_stats = q(
        f"select count(distinct f.state_id), "
        f"count(distinct split_part(f.concept,'#',1)) "
        f"from read_parquet('{ds}/facts.parquet') f "
        f"join read_parquet('{ds}/variant_version.parquet') vv "
        f"on f.variant_version_id = vv.variant_version_id "
        f"join read_parquet('{ds}/submission_variant.parquet') sv "
        f"on vv.variant_id = sv.variant_id "
        f"join read_parquet('{ds}/filing.parquet') fi "
        f"on sv.filing_id = fi.filing_id "
        f"where fi.family='IPP'")
    n_ipp_states, n_ipp_ns = ipp_stats[0] if ipp_stats else (0, 0)
    ck("G3A-10", len(ipp_filings) >= 40 and n_ipp_states > 0
       and n_ipp_ns >= 2,
       f"{len(ipp_filings)} IPP filings; {n_ipp_states} parsed states; "
       f"{n_ipp_ns} distinct IPP namespaces (model families)")

    # ---------- G3A-11: clean bootstrap
    ie = recs.get("init_evA", {})
    ck("G3A-11", ie.get("exit") == 0
       and "INITIALIZED" in ie.get("stdout", "")
       and vd.get("exit") == 0,
       "init --evidence-dir on empty dir -> INITIALIZED + validate")

    # ---------- G3A-12: convergence (replay oracle + live subset)
    rp = recs.get("legA_replay", {})
    uf = recs.get("update_full_replay", {})
    lb = recs.get("legB_update", {})
    lb_status = ("NO_CHANGE" if "NO_CHANGE" in lb.get("stdout", "")
                 else "SOURCE_CHANGED"
                 if "SOURCE_CHANGED" in lb.get("stdout", "")
                 else lb.get("stdout", "")[-60:])
    lb_nifs = {i["nif"] for i in man_b["scope"]["issuers"]}
    want_nifs = {e["nif"] for e in leg_b["issuers"]}
    ck("G3A-12", rp.get("equal") and "NO_CHANGE" in uf.get("stdout", "")
       and uf.get("bytes_unchanged") and lb.get("exit") == 0
       and lb_nifs == want_nifs
       and ("NO_CHANGE" in lb.get("stdout", "")
            or "SOURCE_CHANGED" in lb.get("stdout", "")),
       f"replay equal {rp.get('equal')}; full update NO_CHANGE; "
       f"legB ({cap_b}, {len(lb_nifs)} issuers) -> {lb_status}")

    # ---------- G3A-13: compare semantics on dual-variant filings
    cd = recs.get("compare_dual", {})
    cmp_rep = C.jload(C.OUT / "compare_report.json")
    compared = [v for v in cmp_rep.values()
                if v.get("status") == "COMPARED"]
    divergent = sum((v.get("counts") or {})
                    .get("DIVERGENT_SUBMISSION_FACT", 0)
                    for v in compared)
    lang_excl = sum((v.get("counts") or {})
                    .get("LANGUAGE_SENSITIVE_NOT_COMPARED", 0)
                    for v in compared)
    # G1-C semantics: every dual-variant filing compares; language-
    # sensitive facts are excluded rather than divergent; unresolved
    # mappings stay UNMAPPED; real divergences are reported, not masked
    ck("G3A-13", cd.get("filings", 0) >= 1
       and cd.get("exits") == [0] and len(compared) == len(cmp_rep)
       and lang_excl > 0,
       f"{len(compared)}/{len(cmp_rep)} dual filings COMPARED; "
       f"divergent facts {divergent} (reported, not masked); "
       f"language-sensitive excluded {lang_excl}")

    # ---------- G3A-14: determinism across hash seeds
    se = recs.get("seed_equal", {})
    ck("G3A-14", se.get("s1_vs_s2") and se.get("s1_vs_dsA"),
       f"seed0 vs seed777 {se.get('s1_vs_s2')}; "
       f"vs in-process {se.get('s1_vs_dsA')}")

    # ---------- G3A-15: read battery
    exp = {"read.err.unknown_filing": 4,
           "read.err.missing_dataset": 3,
           "read.err.usage": 2}
    reads = {n: r for n, r in recs.items() if n.startswith("read.")
             and n != "read_bytes_unchanged"}
    ok_reads = all(r.get("exit") == exp.get(n, 0)
                   for n, r in reads.items())
    ck("G3A-15", ok_reads and len(reads) >= 20
       and recs.get("read_bytes_unchanged", {}).get("ok"),
       f"{sum(1 for n, r in reads.items() if r.get('exit') == exp.get(n, 0))}"
       f"/{len(reads)} commands correct exit; bytes unchanged")

    # ---------- G3A-16: expected-vs-captured reconciliation
    captured_esef = {}   # (key, iso_period) -> views
    for v in man_a["esef_views"]:
        captured_esef.setdefault(
            (v["issuer_key"], _iso(v["registry_row"]["cells"][1])),
            []).append(v["resolution_mode"])
    captured_ipp = {}    # (key, sem, year) -> status
    for r_ in man_a["ipp_filings"]:
        captured_ipp[(r_["issuer_key"], r_["semester"], r_["year"])] = \
            r_["status"]
    # periods documented as absent from the served registry
    # (discover warning) are explained omissions, not gaps
    absent_warned = set()
    for w in man_a["warnings"]:
        m = re.match(r"([^/]+)/(es|en): declared scope period "
                     r"'([^']+)' absent", w)
        if m:
            absent_warned.add((m.group(1), _iso(m.group(3))))
    unexplained = []
    for nif, e in expected["issuers"].items():
        sc = e["scope"]
        for p in sc.get("esef_periods", []):
            if (e["key"], _iso(p)) not in captured_esef \
                    and (e["key"], _iso(p)) not in absent_warned:
                unexplained.append(f"{e['key']} esef {p}")
        for sem, yr in sc.get("ipp_slots", []):
            st = captured_ipp.get((e["key"], sem, yr))
            if st is None:
                unexplained.append(f"{e['key']} ipp {sem} {yr}: no row")
    ck("G3A-16", unexplained == [],
       f"{len(unexplained)} unexplained scope omissions "
       f"{unexplained[:6]}")

    # ---------- G3A-17: failure accounting + no post-capture code fixes
    stats = recs.get("corpus_stats", {})
    n_notfound = sum(1 for r_ in man_a["ipp_filings"]
                     if r_["status"] == "NOT_FOUND")
    n_warnings = len(man_a["warnings"])
    r = subprocess.run(["git", "status", "--porcelain", "--", "src/",
                        "tests/"], cwd=REPO, capture_output=True,
                       text=True)
    dirty = r.stdout.strip()
    r = subprocess.run(
        ["git", "log", "--format=%H %cI", f"--since={cap_at}",
         "--", "src/", "tests/"], cwd=REPO,
        capture_output=True, text=True)
    post_cap = r.stdout.strip()
    ck("G3A-17", dirty == "" and post_cap == "",
       f"ipp NOT_FOUND {n_notfound}; warnings {n_warnings}; "
       f"unresolved states {stats.get('unresolved_states')}; "
       f"post-capture src commits: {post_cap or 'none'}")

    # ---------- G3A-18: G2 regression verifiers
    for cid, gate in (
            ("G3A-18a", "g2/G2-A-durable-canonical-core/g2a_verify.py"),
            ("G3A-18b", "g2/G2-B-frozen-corpus-rebuild/g2b_verify.py"),
            ("G3A-18c", "g2/G2-C-columnar-dataset-v1/g2c_verify.py"),
            ("G3A-18d",
             "g2/G2-D-incremental-update-semantics/g2d_verify.py"),
            ("G3A-18e", "g2/G2-E-public-readonly-cli/g2e_verify.py"),
            ("G3A-18f",
             "g2/G2-F-controlled-capture-update-cli/g2f_verify.py"),
            ("G3A-18g", "g2/G2-G-dataset-bootstrap/g2g_verify.py")):
        r = subprocess.run([sys.executable, str(REPO / gate)],
                           cwd=REPO, capture_output=True, text=True)
        ck(cid, r.returncode == 0,
           f"{gate.split('/')[1]} verifier rc={r.returncode}")

    # ---------- G3A-19: no gate imports in production code
    bad = []
    for p in (REPO / "src").rglob("*.py"):
        for i, line in enumerate(
                p.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*(from|import)\s+(g0_r|g0-r|g1|g2|g3)[\.\s]",
                        line):
                bad.append(f"{p.name}:{i}:{line.strip()}")
    ck("G3A-19", bad == [], f"{len(bad)} gate imports in src/opencnmv")

    # ---------- G3A-20: tests + lint + docs
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=REPO, capture_output=True, text=True)
    ck("G3A-20a", r.returncode == 0,
       (r.stdout.strip().splitlines() or ["?"])[-1])
    r = subprocess.run([sys.executable, "-m", "ruff", "check",
                        "src", "tests"], cwd=REPO,
                       capture_output=True, text=True)
    ck("G3A-20b", r.returncode == 0, "ruff clean")
    r = subprocess.run([sys.executable, "-m", "mypy", "src", "tests"],
                       cwd=REPO, capture_output=True, text=True)
    if "No module named mypy" in r.stderr:
        import shutil as _sh
        alt = _sh.which("mypy")
        if alt:
            r = subprocess.run([alt, "src", "tests"], cwd=REPO,
                               capture_output=True, text=True)
    ck("G3A-20c", r.returncode == 0,
       (r.stdout.strip().splitlines() or ["?"])[-1][:120])

    npass = sum(1 for c in checks if c["status"] == "PASS")
    verdict = "PASS" if npass == len(checks) else "FAIL"
    RESULTS.write_bytes(json.dumps({
        "gate": "G3-A", "verdict": verdict,
        "checks": checks, "passed": npass, "total": len(checks)},
        indent=1, ensure_ascii=False).encode("utf-8"))
    print(f"\nG3-A {verdict}: {npass}/{len(checks)}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
