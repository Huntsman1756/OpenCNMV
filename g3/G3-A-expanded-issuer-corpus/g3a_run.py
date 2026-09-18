"""G3-A run legs: expanded-corpus capture, bootstrap, convergence.

    python g3a_run.py            # all legs (leg A + leg B live)
    python g3a_run.py --offline  # skip live legs; replay preserved
                                 # evidence only

Produces under _out/:
    evidence/liveA/     leg A — full 40-issuer capture
    evidence/liveB/     leg B — preregistered 10-issuer recapture
    obs_a.json          leg-A CANONICAL_OBSERVATION_V1
    obs_a_replay.json   offline reassembly of the same run
    obs_b.json          leg-B observation
    ds_a/               bootstrapped COLUMNAR_DATASET_V1
    ds_seed0/ds_seed777 PYTHONHASHSEED reruns
    results.jsonl       per-leg result lines for g3a_verify.py
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import g3a_common as C  # noqa: E402

from opencnmv.cli.main import entry as cli_entry  # noqa: E402
from opencnmv.capture import observe as cobs  # noqa: E402


class deny_network:
    def __enter__(self):
        def blocked(*a, **k):
            raise AssertionError("network access attempt")
        self._p = [mock.patch.object(socket, n, blocked)
                   for n in ("socket", "create_connection",
                             "getaddrinfo", "gethostbyname")]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._p:
            p.stop()


def run_cli(argv: list[str]) -> dict:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            code = cli_entry(argv)
        except SystemExit as e:   # argparse --help / parse errors
            code = e.code if isinstance(e.code, int) else 0
    return {"argv": argv, "exit": code, "stdout": out.getvalue(),
            "stderr": err.getvalue()}


def _cap_id(stdout: str) -> str | None:
    m = re.search(r"capture_id: (\S+)", stdout)
    return m.group(1) if m else None


def _leg_result(tag: str) -> Path:
    return C.OUT / f"{tag}_result.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="skip live legs; reuse preserved evidence")
    args = ap.parse_args()

    C.OUT.mkdir(parents=True, exist_ok=True)
    if C.RESULTS.exists() and not args.offline:
        C.RESULTS.unlink()

    leg_b = C.jload(C.LEG_B)

    # arelle.SocketUtils subclasses socket.socket at module level —
    # importing it inside a socket-denied region would break the class
    # definition, so bind the module first. The denial still covers
    # every opencnmv fetch path (create_connection/getaddrinfo/...).
    import arelle.api.Session  # noqa: F401

    # ------------------------------------------------ leg A: full capture
    legA_res = _leg_result("legA")
    if not args.offline or not legA_res.is_file():
        r = run_cli(["observe", "--evidence-dir", str(C.EV_A),
                     "--issuer-registry", str(C.SAMPLE),
                     "--min-delay", str(C.MIN_DELAY),
                     "--out", str(C.OBS_A),
                     "--taxonomy-dir", str(C.TAX_DIR)])
        C.jwrite(legA_res, {"capture_id": _cap_id(r["stdout"]),
                            "exit": r["exit"],
                            "stderr_tail": r["stderr"][-800:]})
        C.record("legA_observe", **r)
    cap_a = C.jload(legA_res)["capture_id"]

    # ------------------------------------ convergence oracle: offline
    # replay of the preserved leg-A run (no network at all)
    with deny_network():
        obs_replay = cobs.assemble_from_evidence(
            C.EV_A, tax_dir=C.TAX_DIR, run=cap_a)
        C.jwrite(C.OBS_A_REPLAY, obs_replay)
        obs_a = C.jload(C.OBS_A)
        C.record("legA_replay",
                 obs_sha=obs_a.get("observation_sha256"),
                 replay_sha=obs_replay.get("observation_sha256"),
                 equal=obs_replay == obs_a)

        # ------------------------------ G3A-11: clean bootstrap + validate
        if not (C.DS_A / "dataset_manifest.json").is_file():
            r = run_cli(["init", "--dataset", str(C.DS_A),
                         "--evidence-dir", str(C.EV_A),
                         "--taxonomy-dir", str(C.TAX_DIR),
                         "--run", cap_a])
            C.record("init_evA", **r)
        r = run_cli(["dataset", "validate", "--dataset", str(C.DS_A)])
        C.record("validate_dsA", **r)

        # -------------- G3A-12 (oracle leg): update with the leg-A
        # observation -> NO_CHANGE, zero bytes changed
        before = C.dir_hashes(C.DS_A)
        r = run_cli(["update", "--dataset", str(C.DS_A),
                     "--observation", str(C.OBS_A)])
        C.record("update_full_replay", **r,
                 bytes_unchanged=C.dir_hashes(C.DS_A) == before)

    # ----------------------------- leg B: preregistered subset recapture
    legB_res = _leg_result("legB")
    if not args.offline or not legB_res.is_file():
        argv = ["observe", "--evidence-dir", str(C.EV_B),
                "--issuer-registry", str(C.SAMPLE),
                "--min-delay", str(C.MIN_DELAY),
                "--out", str(C.OBS_B),
                "--taxonomy-dir", str(C.TAX_DIR)]
        for e in leg_b["issuers"]:
            argv += ["--issuer", e["nif"]]
        r = run_cli(argv)
        C.jwrite(legB_res, {"capture_id": _cap_id(r["stdout"]),
                            "exit": r["exit"],
                            "stderr_tail": r["stderr"][-800:]})
        C.record("legB_observe", **r)
    cap_b = C.jload(legB_res)["capture_id"]

    # leg-B convergence: live evidence -> dataset rebased assembly ->
    # NO_CHANGE when the source is unchanged (drift => SOURCE_CHANGED)
    with deny_network():
        before = C.dir_hashes(C.DS_A)
        r = run_cli(["update", "--dataset", str(C.DS_A),
                     "--evidence-dir", str(C.EV_B),
                     "--run", cap_b,
                     "--taxonomy-dir", str(C.TAX_DIR)])
        C.record("legB_update", **r,
                 bytes_unchanged=C.dir_hashes(C.DS_A) == before)

    # -------------------- G3A-14: PYTHONHASHSEED reruns (subprocesses)
    for env_seed, dest in (("0", C.DS_S1), ("777", C.DS_S2)):
        if (dest / "dataset_manifest.json").is_file():
            continue
        env = dict(os.environ, PYTHONHASHSEED=env_seed,
                   PYTHONPATH=str(REPO / "src"))
        r = subprocess.run(
            [sys.executable, "-m", "opencnmv", "init",
             "--dataset", str(dest), "--evidence-dir", str(C.EV_A),
             "--taxonomy-dir", str(C.TAX_DIR), "--run", cap_a],
            cwd=REPO, env=env, capture_output=True, text=True)
        C.record(f"init_seed{env_seed}", exit=r.returncode,
                 stdout=r.stdout[-400:], stderr=r.stderr[-400:])
    if (C.DS_S1 / "dataset_manifest.json").is_file() and \
            (C.DS_S2 / "dataset_manifest.json").is_file():
        C.record("seed_equal",
                 s1_vs_s2=C.dir_hashes(C.DS_S1)
                 == C.dir_hashes(C.DS_S2),
                 s1_vs_dsA=C.dir_hashes(C.DS_S1)
                 == C.dir_hashes(C.DS_A))

    # -------------------- G3A-15: G2-E read battery on the expanded ds
    import duckdb  # noqa: E402
    ds = C.DS_A.as_posix()

    def q(s):
        return duckdb.sql(s).fetchall()
    esef_id = q(f"select filing_id from read_parquet('{ds}/filing.parquet')"
                " where family='ESEF_IFA' order by 1 limit 1")[0][0]
    ipp_id = q(f"select filing_id from read_parquet('{ds}/filing.parquet')"
               " where family='IPP' order by 1 limit 1")[0][0]
    fact_id = q(f"select fact_id from read_parquet('{ds}/facts.parquet')"
                " limit 1")[0][0]
    state_id = q(f"select state_id from read_parquet('{ds}/facts.parquet')"
                 " limit 1")[0][0]
    variant = q("select variant_id from "
                f"read_parquet('{ds}/submission_variant.parquet') "
                "limit 1")[0][0]
    art_sha = q(f"select sha256 from read_parquet('{ds}/artifact.parquet')"
                " limit 1")[0][0]
    h2_rows = q(f"select state_id from read_parquet('{ds}/facts.parquet')"
                " where state_id like '%-H2-%' limit 1")
    read_cmds = [
        ("dataset.info", ["--dataset", ds, "dataset", "info"]),
        ("dataset.info.json",
         ["--dataset", ds, "dataset", "info", "--json"]),
        ("dataset.validate",
         ["--dataset", ds, "dataset", "validate"]),
        ("filings", ["--dataset", ds, "filings"]),
        ("filings.jsonl", ["--dataset", ds, "filings", "--jsonl"]),
        ("filings.ipp",
         ["--dataset", ds, "filings", "--family", "IPP"]),
        ("filing.esef", ["--dataset", ds, "filing", esef_id, "--json"]),
        ("filing.ipp", ["--dataset", ds, "filing", ipp_id, "--json"]),
        ("history", ["--dataset", ds, "history", esef_id, "--json"]),
        ("history.variant",
         ["--dataset", ds, "history", variant, "--json"]),
        ("facts.state",
         ["--dataset", ds, "facts", "--state", state_id, "--limit",
          "5"]),
        ("facts.count", ["--dataset", ds, "facts", "--count"]),
        ("fact", ["--dataset", ds, "fact", fact_id, "--json"]),
        ("compare", ["--dataset", ds, "compare", esef_id, "--json"]),
        ("events.all", ["--dataset", ds, "events", "--jsonl"]),
        ("events.filing", ["--dataset", ds, "events", esef_id]),
        ("mappings",
         ["--dataset", ds, "mappings", esef_id, "--json"]),
        ("prov.fact",
         ["--dataset", ds, "provenance", "--fact", fact_id, "--json"]),
        ("prov.artifact",
         ["--dataset", ds, "provenance", "--artifact",
          f"sha256:{art_sha}", "--json"]),
        ("prov.state",
         ["--dataset", ds, "provenance", "--state", state_id,
          "--json"]),
        ("err.unknown_filing",
         ["--dataset", ds, "filing", "cnmv:ifa:00000"]),
        ("err.missing_dataset",
         ["--dataset", str(C.OUT / "nonexistent"), "dataset", "info"]),
        ("err.usage",
         ["--dataset", ds, "filings", "--bogus-flag"]),
    ]
    if h2_rows:
        read_cmds.append(
            ("facts.h2dims",
             ["--dataset", ds, "facts", "--state", h2_rows[0][0],
              "--limit", "5", "--jsonl"]))
    before = C.dir_hashes(C.DS_A)
    with deny_network():
        for name, argv in read_cmds:
            C.record(f"read.{name}", **run_cli(argv))
    C.record("read_bytes_unchanged",
             ok=C.dir_hashes(C.DS_A) == before)

    # -------------------- G3A-13: compare on every dual-variant filing
    dual = q("select filing_id, count(*) c from "
             f"read_parquet('{ds}/submission_variant.parquet') "
             "group by 1 having c > 1 order by 1")
    cmp_report = {}
    with deny_network():
        for fid, _c in dual:
            r = run_cli(["--dataset", ds, "compare", fid, "--json"])
            try:
                cmp_report[fid] = {"exit": r["exit"],
                                   "doc": json.loads(r["stdout"])}
            except json.JSONDecodeError:
                cmp_report[fid] = {"exit": r["exit"], "doc": None,
                                   "stdout_tail": r["stdout"][-300:]}
    C.jwrite(C.OUT / "compare_report.json",
             {k: {"exit": v["exit"],
                  **({"status": v["doc"].get("status"),
                      "counts": v["doc"].get("counts"),
                      "proven_pairs_applied":
                          v["doc"].get("proven_pairs_applied")}
                     if isinstance(v["doc"], dict) else {})}
              for k, v in cmp_report.items()})
    C.record("compare_dual",
             filings=len(dual),
             exits=sorted({v["exit"] for v in cmp_report.items()}))

    # -------------------- corpus-level accounting records
    fams = {"ESEF_IFA": 0, "IPP": 0}
    n_states = 0
    unresolved_states = 0
    for f in obs_a["filings"]:
        fams[f["filing"]["family"]] += 1
        for st in f.get("states", []):
            n_states += 1
            if st.get("unresolved"):
                unresolved_states += 1
    n_ev = q("select count(*) from "
             f"read_parquet('{ds}/version_event.parquet')").fetchone()[0]
    n_map = q("select count(*) from "
              f"read_parquet('{ds}/extension_mapping.parquet')"
              ).fetchone()[0]
    n_variants = q("select count(*) from "
                   f"read_parquet('{ds}/submission_variant.parquet')"
                   ).fetchone()[0]
    n_facts = q("select count(*) from "
                f"read_parquet('{ds}/facts.parquet')").fetchone()[0]
    C.record("corpus_stats",
             filings=len(obs_a["filings"]), esef=fams["ESEF_IFA"],
             ipp=fams["IPP"], variants=n_variants, facts=n_facts,
             version_events=n_ev, extension_mappings=n_map,
             states=n_states, unresolved_states=unresolved_states)

    mans = {}
    for tag, d in (("dsA", C.DS_A), ("s1", C.DS_S1), ("s2", C.DS_S2)):
        m = C.jload(d / "dataset_manifest.json")
        mans[tag] = m["corpus_logical_sha256"]
    C.record("corpus_hashes", **mans,
             all_equal=len(set(mans.values())) == 1)

    print("g3a_run complete ->", C.RESULTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
