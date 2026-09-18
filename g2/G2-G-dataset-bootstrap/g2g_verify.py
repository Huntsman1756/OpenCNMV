"""G2-G verifier: evaluates the preregistered B1-B18 acceptance matrix
over the artifacts produced by g2g_run.py plus the regression verifiers
of G2-A..F.

    python g2g_verify.py              evaluate existing _out artifacts
    python g2g_verify.py --run-all    run g2g_run.py first (needs network
                                    for the bounded live smoke; pass
                                    --offline to reuse preserved evidence)

Writes g2g_verify_results.json (gate root, committed). PASS requires
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

import g2g_common as C  # noqa: E402

RESULTS = HERE / "g2g_verify_results.json"


def main() -> int:
    if "--run-all" in sys.argv:
        extra = ["--offline"] if "--offline" in sys.argv else []
        r = subprocess.run([sys.executable, str(HERE / "g2g_run.py"),
                            *extra], cwd=REPO)
        if r.returncode != 0:
            print("g2g_run.py failed")
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

    # B1 init --observation -> valid dataset
    io_, vo = recs.get("init_obs", {}), recs.get("validate_obs", {})
    ck("B1", io_.get("exit") == 0 and vo.get("exit") == 0
       and "FAIL" not in vo.get("stdout", "")
       and "INITIALIZED" in io_.get("stdout", ""),
       f"init exit {io_.get('exit')}; validate clean")

    # B2 evidence-dir replay == observation bootstrap (byte-identical)
    ck("B2", recs.get("init_ev", {}).get("exit") == 0
       and recs.get("init_ev_equal", {}).get("ok"),
       "init --evidence-dir --taxonomy-dir produces the identical "
       "dataset as --observation")

    # B3 byte-identical across reruns and hash seeds
    se = recs.get("seed_equal", {})
    ck("B3", se.get("s0_vs_777") and se.get("s0_vs_obs"),
       f"PYTHONHASHSEED 0 vs 777 identical: {se.get('s0_vs_777')}; "
       f"vs in-process run: {se.get('s0_vs_obs')}")

    # B4 no base consulted: no --base surface; explicit --dataset and a
    # source are both required
    hp = recs.get("init_help", {})
    ck("B4", hp.get("exit") == 0 and "--base" not in hp.get("stdout", "")
       and recs.get("init_no_dataset", {}).get("exit") == 2
       and recs.get("init_no_source", {}).get("exit") == 2,
       "no --base flag; missing --dataset/--source -> exit 2")

    # B5 zero gate imports in production code
    bad = recs.get("gate_imports", {}).get("bad", ["<missing>"])
    ck("B5", bad == [], f"{len(bad)} gate imports in src/opencnmv")

    # B6 extras_json absent, dataset still fully valid + served
    ck("B6", recs.get("extras_absent", {}).get("nonnull_extras") == 0
       and vo.get("exit") == 0,
       f"non-null filing.extras_json rows: "
       f"{recs.get('extras_absent', {}).get('nonnull_extras')} "
       "(no curated overlay required or fabricated)")

    # B7 bounded live smoke + offline replay identical
    il = recs.get("init_live", {})
    cap = recs.get("init_live_capture_id", {})
    ck("B7", il.get("exit") == 0 and cap.get("capture_id")
       and cap.get("artifacts", 0) > 0 and cap.get("runs")
       and recs.get("init_live_replay", {}).get("exit") == 0
       and recs.get("live_replay_equal", {}).get("ok"),
       f"init --live -> {cap.get('capture_id')} "
       f"({cap.get('artifacts')} artifacts preserved); offline replay "
       f"byte-identical: {recs.get('live_replay_equal', {}).get('ok')}")

    # B8 every G2-E read-only command on the bootstrapped dataset
    exp = {"read.err.unknown_filing": 4, "read.err.unknown_fact": 4,
           "read.err.missing_dataset": 3, "read.err.usage": 2}
    reads = {n: r for n, r in recs.items() if n.startswith("read.")
             and n != "read_bytes_unchanged"}
    ok_reads = all(r.get("exit") == exp.get(n, 0)
                   for n, r in reads.items())
    ck("B8", ok_reads and len(reads) >= 24
       and recs.get("read_bytes_unchanged", {}).get("ok"),
       f"{sum(1 for n, r in reads.items() if r.get('exit') == exp.get(n, 0))}"
       f"/{len(reads)} commands correct exit; dataset bytes unchanged")

    # B9 update same observation -> NO_CHANGE, zero bytes
    uf = recs.get("update_fixpoint", {})
    ck("B9", "NO_CHANGE" in uf.get("stdout", "")
       and recs.get("fixpoint_bytes_unchanged", {}).get("ok"),
       "bootstrap is the update fixpoint: NO_CHANGE, byte-identical")

    # B10 non-empty destination refused; no overwrite flag
    ck("B10", recs.get("init_nonempty", {}).get("exit") == 2
       and "--overwrite" not in hp.get("stdout", "")
       and "--replace" not in hp.get("stdout", ""),
       f"init onto non-empty dest -> exit "
       f"{recs.get('init_nonempty', {}).get('exit')} "
       "(no overwrite option exists)")

    # B11 injected mid-bootstrap failure -> nothing publishable
    inj = all(recs.get(f"inject_{h}", {}).get("raised")
            and not recs.get(f"inject_{h}", {}).get("dest_exists")
            and recs.get(f"inject_{h}", {}).get("staging_left") == 0
            for h in ("during_table:facts", "before_publish"))
    ck("B11", inj, "injected failures leave no dataset and no staging")

    # B12 no absolute paths; deterministic corpus hash
    nap = recs.get("no_abs_paths", {})
    ch = recs.get("corpus_hashes", {})
    ck("B12", nap.get("manifest_clean") and nap.get("prov_relative")
       and nap.get("prov_rows", 0) > 0 and ch.get("all_equal"),
       f"manifest clean; {nap.get('prov_rows')} relative prov paths; "
       f"corpus {ch.get('obs', '')[:12]}… equal across "
       f"obs/ev/seeds: {ch.get('all_equal')}")

    # B13 semantic parity vs frozen corpus + structural checks
    sm = recs.get("semantics", {})
    ibe_ok = sm.get("ibe_variants") and all(
        v.endswith("#es") for v in sm["ibe_variants"])
    ck("B13", sm.get("filings") == 21 and sm.get("all_equal")
       and sm.get("esef") == 6 and sm.get("ipp") == 15
       and sm.get("version_events", 0) > 0
       and sm.get("extension_mappings", 0) > 0 and ibe_ok,
       f"21 filings equal to G2-C (scoped rows, documented exclusions); "
       f"ESEF={sm.get('esef')} IPP={sm.get('ipp')}; "
       f"events={sm.get('version_events')} "
       f"mappings={sm.get('extension_mappings')}; "
       f"IBE variants {sm.get('ibe_variants')}")

    # B14 installed-wheel external-input smoke
    whl = C.OUT / "wheel_smoke_g.json"
    whl = C.jload(whl) if whl.is_file() else None
    ck("B14", bool(whl and whl["ok"]),
       "wheel init from external evidence+taxonomy: "
       + (whl["summary"] if whl
          else "wheel_smoke_g.json missing — run g2g_wheel.py"))

    # B15 deterministic output + exit vocabulary
    jd = recs.get("json_determinism", {})
    ux = all(recs.get(n, {}).get("exit") == 2 for n in
             ("ux_obs_plus_ev", "ux_ev_no_tax", "ux_live_no_ev",
              "ux_issuer_no_live", "ux_family_no_live",
              "ux_mindelay_obs", "ux_run_with_live"))
    codes = {"ok": io_.get("exit"), "usage":
             recs.get("init_nonempty", {}).get("exit")}
    ck("B15", jd.get("same") and jd.get("exit") == 0
       and jd.get("parseable") and ux
       and codes["ok"] == 0 and codes["usage"] == 2,
       f"identical repeated --json; 7 usage-error combos -> exit 2; "
       f"codes observed: {codes}")

    # B16 tests + ruff + mypy
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=REPO, capture_output=True, text=True)
    ck("B16a", r.returncode == 0,
       (r.stdout.strip().splitlines() or ["?"])[-1])
    r = subprocess.run([sys.executable, "-m", "ruff", "check",
                        "src", "tests"], cwd=REPO,
                       capture_output=True, text=True)
    ck("B16b", r.returncode == 0, "ruff clean")
    r = subprocess.run([sys.executable, "-m", "mypy", "src", "tests"],
                       cwd=REPO, capture_output=True, text=True)
    if "No module named mypy" in r.stderr:
        import shutil as _sh
        alt = _sh.which("mypy")
        if alt:
            r = subprocess.run([alt, "src", "tests"], cwd=REPO,
                               capture_output=True, text=True)
    ck("B16c", r.returncode == 0,
       (r.stdout.strip().splitlines() or ["?"])[-1][:120])

    # B17 regression verifiers G2-A..F
    for cid, gate in (("B17a", "g2/G2-A-durable-canonical-core/"
                              "g2a_verify.py"),
                      ("B17b", "g2/G2-B-frozen-corpus-rebuild/"
                               "g2b_verify.py"),
                      ("B17c", "g2/G2-C-columnar-dataset-v1/"
                               "g2c_verify.py"),
                      ("B17d", "g2/G2-D-incremental-update-semantics/"
                               "g2d_verify.py"),
                      ("B17e", "g2/G2-E-public-readonly-cli/"
                               "g2e_verify.py"),
                      ("B17f", "g2/G2-F-controlled-capture-update-cli/"
                               "g2f_verify.py")):
        r = subprocess.run([sys.executable, str(REPO / gate)],
                           cwd=REPO, capture_output=True, text=True)
        ck(cid, r.returncode == 0,
           f"{gate.split('/')[1]} verifier rc={r.returncode}")

    # B18 docs
    cli = (REPO / "docs/CLI.md").read_text(encoding="utf-8")
    status = (REPO / "docs/STATUS.md").read_text(encoding="utf-8")
    g2 = (REPO / "docs/G2.md").read_text(encoding="utf-8")
    ck("B18", "init" in cli and "G2-G" in status and "G2-G" in g2,
       "docs/CLI.md + docs/STATUS.md + docs/G2.md updated")

    npass = sum(1 for c in checks if c["status"] == "PASS")
    verdict = "PASS" if npass == len(checks) else "FAIL"
    RESULTS.write_bytes(json.dumps({
        "gate": "G2-G", "verdict": verdict,
        "checks": checks, "passed": npass, "total": len(checks)},
        indent=1, ensure_ascii=False).encode("utf-8"))
    print(f"\nG2-G {verdict}: {npass}/{len(checks)}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
