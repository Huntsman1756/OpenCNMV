# G2-B — FULL_FROZEN_CORPUS_REBUILD orchestrator.
#
# Rebuilds all 25 frozen XBRL states (10 ESEF variant packages + 15 IPP
# instances) through the PRODUCTION path only:
#   opencnmv.xbrl.arelle -> opencnmv.canonicalize.facts
#
# RUN A: PYTHONHASHSEED=17   RUN B: PYTHONHASHSEED=991
# Both runs: fresh Arelle profile/cache (XDG_CONFIG_HOME + HOME/USERPROFILE/
# APPDATA/LOCALAPPDATA + TEMP/TMP redirected to run-local dirs), socket
# deny-all inside every worker, meta-path blocker against g0-r//g1/ imports.
#
# Frozen gate outputs (R11/R12/G1-B facts.jsonl + model_summary.json) are
# read as regression ORACLES only — never imported as code.
import json, os, subprocess, sys, zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "_out"
sys.path.insert(0, str(REPO / "src"))
from opencnmv.provenance.hashes import sha256_file  # noqa: E402


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def isolated_env(run_dir: Path, hashseed: int) -> dict:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(hashseed)
    env["PYTHONIOENCODING"] = "utf-8"
    for var, sub in (("XDG_CONFIG_HOME", "xdg"),
                     ("HOME", "home"), ("USERPROFILE", "home"),
                     ("APPDATA", "appdata"), ("LOCALAPPDATA", "appdata"),
                     ("TEMP", "tmp"), ("TMP", "tmp"), ("TMPDIR", "tmp")):
        d = run_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        env[var] = str(d)
    return env


def run_parse(entry: dict, run_dir: Path, env: dict,
              override_packages=None) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    spec = dict(entry)
    spec["out_dir"] = str(run_dir)
    spec["tax_dir"] = str(REPO / "g0-r/R10-taxonomy-pinning/evidence")
    spec["artifact"] = str(REPO / entry["artifact"])
    if override_packages is not None:
        spec["override_packages"] = [str(REPO / p) for p in override_packages]
    spec_path = run_dir / f"{entry['id']}.spec.json"
    spec_path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(HERE / "g2b_parse_one.py"),
         str(spec_path)],
        env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if r.returncode != 0:
        return {"filing": entry["id"], "status": "WORKER_CRASH",
                "stderr": r.stderr[-2000:]}
    line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}"
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"filing": entry["id"], "status": "WORKER_BAD_OUTPUT",
                "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}


def main():
    corpus = load_json(HERE / "g2b_corpus.json")
    inputs = load_json(HERE / "g2b_inputs.json")

    # B1 — verify every pinned input before parsing anything
    pin_errors = []
    for group in ("artifacts", "taxonomy_packages", "oracles"):
        for key, rec in inputs[group].items():
            p = REPO / rec["path"]
            if not p.is_file() or sha256_file(p).upper() != rec["sha256"]:
                pin_errors.append(key)
    print(f"B1 input pins: {len(pin_errors)} mismatches", flush=True)

    results = {"B1_pin_mismatches": pin_errors, "runs": {},
               "negative_controls": {}}

    for run_name, hashseed in (("A", 17), ("B", 991)):
        run_dir = OUT / f"run{run_name}"
        run_dir.mkdir(parents=True, exist_ok=True)
        env = isolated_env(run_dir / "_isolate", hashseed)
        run_res = {}
        for e in corpus:
            print(f"[run{run_name}] {e['id']}", flush=True)
            run_res[e["id"]] = run_parse(e, run_dir, env)
            print("   ", json.dumps(run_res[e["id"]])[:240], flush=True)
        results["runs"][run_name] = run_res
        (run_dir / "run_results.json").write_bytes(
            json.dumps(run_res, indent=1, ensure_ascii=False).encode("utf-8"))

    # B8 — negative dependency controls (run-A isolation)
    neg_dir = OUT / "_negative_controls"
    neg_dir.mkdir(parents=True, exist_ok=True)
    env = isolated_env(neg_dir / "_isolate", 17)

    # ESEF minus the ESMA ESEF taxonomy package -> DTS must NOT resolve cleanly
    e = next(x for x in corpus if x["id"] == "SAN-FY2024-es")
    drop = "g0-r/R10-taxonomy-pinning/evidence/esef_taxonomy_2022_v1.1.zip"
    kept = [f"g0-r/R10-taxonomy-pinning/evidence/{n}" for n in
            ("ifrs-full_ifrs-2022-03-24-opencnmv-pkg.zip",
             "xbrl-lei-2020-07-02-opencnmv-pkg.zip")]
    results["negative_controls"]["esef_missing_esef_taxonomy"] = run_parse(
        {**e, "id": "NEG-esef-missing-tax"}, neg_dir / "esef", env,
        override_packages=kept)
    results["negative_controls"]["esef_missing_esef_taxonomy"]["dropped"] = drop

    # IPP minus xl/xlink (www.xbrl.org/* entries) -> must NOT resolve cleanly
    e = next(x for x in corpus if x["id"] == "SAN-H1-2024")
    ipp_pkg = REPO / "g0-r/R10-taxonomy-pinning/evidence/cnmv-ipp-2019-01-01-opencnmv-pkg.zip"
    stripped = neg_dir / "ipp-pkg-stripped.zip"
    with zipfile.ZipFile(ipp_pkg) as zin, \
            zipfile.ZipFile(stripped, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if "/www.xbrl.org/" in item.filename:
                continue
            zout.writestr(item, zin.read(item.filename))
    results["negative_controls"]["ipp_missing_xlink"] = run_parse(
        {**e, "id": "NEG-ipp-missing-xlink"}, neg_dir / "ipp", env,
        override_packages=[str(stripped)])

    (OUT / "rebuild_results.json").write_bytes(
        json.dumps(results, indent=1, ensure_ascii=False).encode("utf-8"))
    print("wrote", OUT / "rebuild_results.json")


if __name__ == "__main__":
    main()
