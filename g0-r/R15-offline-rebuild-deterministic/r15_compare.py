# R15 — OFFLINE_REBUILD_DETERMINISTIC (orchestrator + comparator)
#
#   OFFLINE A   clean temp root, empty Arelle cache (TMP redirect),
#               PYTHONHASHSEED=11, dead proxy env, socket deny-all sentinel
#   OFFLINE B   same, PYTHONHASHSEED=999
#   STARVE-ESEF SAN-FY2025 without esef_taxonomy_2024.zip  -> MUST FAIL
#   STARVE-IPP  SAN-H1-2024 with xl-2003-12-31.xsd removed from the derived
#               IPP package -> MUST FAIL or expose builtin-cache fallback
#
# Triple binding on full runs:  A == B,  A == R11/R12 committed evidence,
# A == R14 canonical projections (levels derivable from the frozen bundle).

import hashlib, json, os, re, subprocess, sys
from pathlib import Path

GATE = Path(__file__).resolve().parent
REPO = GATE.parents[1]
EV = GATE / "evidence"
RUNS = GATE / "_runs"


def _norm_media(obj):
    """Canonicalize media_type to the bare MediaType (R7 stored 'application/zip';
    R14 recorded the full Content-Type header which may carry parameters)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "media_type" and isinstance(v, str):
                out[k] = v.split(";")[0].strip().lower()
            elif k == "stable_final_url" and isinstance(v, str):
                # percent-escape case is not semantic (requests vs HttpClient)
                out[k] = re.sub(r"%([0-9a-fA-F]{2})",
                                lambda m: "%" + m.group(1).upper(), v)
            else:
                out[k] = _norm_media(v)
        return out
    if isinstance(obj, list):
        return [_norm_media(x) for x in obj]
    return obj


def canon_sha(p: Path) -> str:
    obj = _norm_media(json.loads(p.read_text(encoding="utf-8")))
    return hashlib.sha256(json.dumps(
        obj, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def spawn(args, root: Path, seed: str):
    tmp = root / "local" / "temp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = seed
    env["TMP"] = env["TEMP"] = str(tmp)
    # redirect every user-profile root into the run dir: Arelle consulted
    # %LOCALAPPDATA%\Arelle\plugins.json even with TMP redirected (found by
    # the read audit) — the run must see an empty profile, not the user's
    for var in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME"):
        env[var] = str(root / "profile")
    env["HTTP_PROXY"] = env["HTTPS_PROXY"] = "http://127.0.0.1:9"  # dead proxy
    p = subprocess.run([sys.executable, str(GATE / "r15_rebuild.py"),
                        *args, "--root", str(root)],
                       env=env, cwd=str(REPO))
    return p.returncode


def main() -> int:
    EV.mkdir(exist_ok=True)
    if "--compare-only" not in sys.argv:
        for run, seed in (("A", "11"), ("B", "999")):
            rc = spawn(["--mode", "full"], RUNS / run, seed)
            if rc != 0:
                raise SystemExit(f"offline run {run} rc={rc}")
        for run, seed, mode in (("S1", "11", "starve-esef"),
                                ("S2", "11", "starve-ipp-xl")):
            rc = spawn(["--mode", mode], RUNS / run, seed)
            if rc != 0:
                raise SystemExit(f"starvation {mode} rc={rc}")

    res = {"levels": {}}
    for lv in ("artifact_manifest", "taxonomy", "events", "facts_index",
               "source_state"):
        pa, pb = RUNS / "A/out" / f"{lv}.json", RUNS / "B/out" / f"{lv}.json"
        ha, hb = canon_sha(pa), canon_sha(pb)
        res["levels"][lv] = {"offline_A": ha, "offline_B": hb, "A_eq_B": ha == hb}
        print(f"{lv:20s} A {'==' if ha == hb else '!='} B  {ha[:14]}")

    # vs R14 runA canonical projections (levels derivable offline only)
    r14a = REPO / "g0-r/R14-online-capture-deterministic/evidence/runA"
    res["vs_r14"] = {}
    for lv in ("artifact_manifest", "taxonomy", "events", "facts_index",
               "source_state"):
        h14, h15 = canon_sha(r14a / f"{lv}.json"), canon_sha(
            RUNS / "A/out" / f"{lv}.json")
        res["vs_r14"][lv] = {"r14": h14, "r15_A": h15, "equal": h14 == h15}
        print(f"vs R14 {lv:16s} {'==' if h14 == h15 else '!='}  {h15[:14]}")

    # vs committed R11/R12 fact inventories
    fa = json.loads((RUNS / "A/out/facts_index.json").read_text(encoding="utf-8"))
    prev = {}
    for gate in ("R11-esef-arelle-parse", "R12-ipp-arelle-parse"):
        for p in (REPO / "g0-r" / gate / "evidence").glob("*.facts.jsonl"):
            prev[p.name.split(".")[0]] = hashlib.sha256(
                p.read_bytes()).hexdigest().upper()
    res["facts_vs_R11_R12"] = {f: prev.get(f) == fa[f]["facts_jsonl_sha256"]
                               for f in sorted(fa)}
    res["facts_equal_prior"] = (
        f"{sum(res['facts_vs_R11_R12'].values())}/{len(fa)}")

    # run-level evidence
    ra = json.loads((RUNS / "A/out/r15_run_result.json").read_text(encoding="utf-8"))
    rb = json.loads((RUNS / "B/out/r15_run_result.json").read_text(encoding="utf-8"))
    s1 = json.loads((RUNS / "S1/out/r15_run_result.json").read_text(encoding="utf-8"))
    s2 = json.loads((RUNS / "S2/out/r15_run_result.json").read_text(encoding="utf-8"))
    res["run_evidence"] = {"A": ra, "B": rb}
    res["starvation"] = {"starve-esef": s1.get("starvation"),
                         "starve-ipp-xl": s2.get("starvation")}

    matrix = {
        "network_block_verified": ra["network_block_verified"]
                                  and rb["network_block_verified"],
        "preflight_unguarded_reachable":
            all(v == "REACHABLE" for v in ra["preflight_unguarded"].values()),
        "external_connect_attempts_after_guard":
            len(ra["external_connect_attempts_after_guard"])
            + len(rb["external_connect_attempts_after_guard"]),
        "unapproved_file_reads":
            ra["unapproved_file_reads_count"] + rb["unapproved_file_reads_count"],
        "input_verification_mismatches":
            ra["input_verification"]["mismatches"]
            + rb["input_verification"]["mismatches"],
        "filings_parsed": len(fa),
        "ioerr_total": sum(v.get("ioerr") or 0 for v in fa.values()),
        "ctrlA_all_equal": all(v.get("ctrlA") for v in fa.values()),
        "offline_A_eq_B_all_levels": all(
            v["A_eq_B"] for v in res["levels"].values()),
        "r15_A_eq_r14_all_levels": all(
            v["equal"] for v in res["vs_r14"].values()),
        "facts_equal_prior_gates": res["facts_equal_prior"] == f"{len(fa)}/{len(fa)}",
        "starve_esef_failed_as_expected":
            s1.get("starvation", {}).get("outcome") == "FAILED_AS_EXPECTED",
        "starve_ipp_xl_outcome":
            s2.get("starvation", {}).get("outcome"),
    }
    res["acceptance"] = matrix
    ok = (matrix["network_block_verified"]
          and matrix["preflight_unguarded_reachable"]
          and matrix["external_connect_attempts_after_guard"] == 0
          and matrix["input_verification_mismatches"] == 0
          and matrix["filings_parsed"] == 21
          and matrix["ioerr_total"] == 0
          and matrix["ctrlA_all_equal"]
          and matrix["offline_A_eq_B_all_levels"]
          and matrix["r15_A_eq_r14_all_levels"]
          and matrix["facts_equal_prior_gates"]
          and matrix["starve_esef_failed_as_expected"])
    res["verdict"] = "PASS" if ok else "FAIL"
    (EV / "r15_results.json").write_text(
        json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    for run in ("A", "B"):
        d = EV / f"offline{run}"
        d.mkdir(exist_ok=True)
        for lv in ("artifact_manifest", "taxonomy", "events", "facts_index",
                   "source_state", "r15_run_result"):
            src = RUNS / run / "out" / f"{lv}.json"
            if src.exists():
                (d / f"{lv}.json").write_bytes(src.read_bytes())
    for run in ("S1", "S2"):
        (EV / f"starvation_{run}.json").write_bytes(
            (RUNS / run / "out/r15_run_result.json").read_bytes())
    print(json.dumps(matrix, indent=2, ensure_ascii=False))
    print("verdict:", res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
