"""G2-G run step: bootstrap legs over preserved G2-F evidence.

    python g2g_run.py             # all legs (bounded live leg included)
    python g2g_run.py --offline   # skip the init --live smoke

Produces under _out/:
    ds_obs/             init --observation result (deterministic oracle)
    ds_ev/              init --evidence-dir result (full liveA replay)
    ds_seed0/, ds_seed777/   PYTHONHASHSEED subprocess reruns
    evidence/liveInit/  bounded init --live capture output
    ds_live/, ds_live_replay/
    obs_input.json      staged CANONICAL_OBSERVATION_V1 (G2-F product)
    results.jsonl       per-leg result lines for g2g_verify.py
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest.mock as mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import g2g_common as C  # noqa: E402

from opencnmv.cli.main import entry as cli_entry  # noqa: E402
from opencnmv.update import bootstrap as uboot  # noqa: E402
from opencnmv.update import observe as uobs  # noqa: E402


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


def _clean(d: Path) -> None:
    if d.exists():
        shutil.rmtree(d)


def _is_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="skip the bounded init --live smoke")
    args = ap.parse_args()

    C.OUT.mkdir(parents=True, exist_ok=True)
    # --offline appends: the live leg's record must survive (same rule
    # as g2f_run); the verifier resolves duplicates to the last line.
    if C.RESULTS.exists() and not args.offline:
        C.RESULTS.unlink()

    # stage the replayable observation input (a product of the public
    # G2-F observe/assemble route — not a dataset copy)
    if not C.OBS_IN.is_file():
        shutil.copy(C.G2F_OBS_BOOT, C.OBS_IN)
    obs_doc = uobs.load(C.OBS_IN)

    # --offline reruns may reuse the already-built datasets (they are
    # deterministic products of the same inputs); a fresh run always
    # rebuilds them.
    rebuild = (not args.offline
               or not (C.DS_OBS / "dataset_manifest.json").is_file()
               or not (C.DS_EV / "dataset_manifest.json").is_file())
    if rebuild:
        for d in (C.DS_OBS, C.DS_EV, C.DS_S0, C.DS_S777):
            _clean(d)

    # arelle.SocketUtils subclasses socket.socket at module level —
    # importing it inside a socket-denied region would break the class
    # definition, so bind the module first. The denial still covers
    # every opencnmv fetch path (create_connection/getaddrinfo/...).
    import arelle.api.Session  # noqa: F401

    with deny_network():
        if rebuild:
            # ---- B1: init --observation on an empty dir
            r = run_cli(["init", "--dataset", str(C.DS_OBS),
                         "--observation", str(C.OBS_IN)])
            C.record("init_obs", **r)
            r = run_cli(["dataset", "validate", "--dataset",
                         str(C.DS_OBS)])
            C.record("validate_obs", **r)
        hashes_obs = C.dir_hashes(C.DS_OBS)
        C.jwrite(C.OUT / "ds_obs_hashes.json", hashes_obs)

        if rebuild:
            # ---- B2: init --evidence-dir --taxonomy-dir (full liveA
            # replay, run pinned) -> identical dataset bytes
            r = run_cli(["init", "--dataset", str(C.DS_EV),
                         "--evidence-dir", str(C.EV_A),
                         "--taxonomy-dir", str(C.TAX_DIR),
                         "--run", C.run_a_id()])
            C.record("init_ev", **r)
            C.record("init_ev_equal",
                     ok=C.dir_hashes(C.DS_EV) == hashes_obs)

        # ---- B4: no base consulted — CLI surface exposes no --base;
        # missing --dataset and missing source are usage errors
        r = run_cli(["init", "--help"])
        C.record("init_help", **r)
        r = run_cli(["init", "--observation", str(C.OBS_IN)])
        C.record("init_no_dataset", **r)
        r = run_cli(["init", "--dataset", str(C.OUT / "ds_nosrc")])
        C.record("init_no_source", **r)

        # ---- usage-error matrix (exit vocabulary)
        usage_cases = {
            "ux_obs_plus_ev": ["init", "--dataset", "x",
                               "--observation", str(C.OBS_IN),
                               "--evidence-dir", "y"],
            "ux_ev_no_tax": ["init", "--dataset", "x",
                             "--evidence-dir", str(C.EV_A)],
            "ux_live_no_ev": ["init", "--dataset", "x", "--live",
                              "--taxonomy-dir", str(C.TAX_DIR)],
            "ux_issuer_no_live": ["init", "--dataset", "x",
                                  "--observation", str(C.OBS_IN),
                                  "--issuer", "A-48010615"],
            "ux_family_no_live": ["init", "--dataset", "x",
                                  "--evidence-dir", str(C.EV_A),
                                  "--taxonomy-dir", str(C.TAX_DIR),
                                  "--family", "ipp"],
            "ux_mindelay_obs": ["init", "--dataset", "x",
                                "--observation", str(C.OBS_IN),
                                "--min-delay", "1"],
            "ux_run_with_live": ["init", "--dataset", "x", "--live",
                                 "--evidence-dir", str(C.EV_A),
                                 "--taxonomy-dir", str(C.TAX_DIR),
                                 "--run", "cap-x"],
        }
        for name, argv in usage_cases.items():
            C.record(name, **run_cli(argv))

        # ---- B10: init onto the now non-empty destination fails
        r = run_cli(["init", "--dataset", str(C.DS_OBS),
                     "--observation", str(C.OBS_IN)])
        C.record("init_nonempty", **r)

        # ---- B15: deterministic --json (same dest path, removed
        # between runs so stdout is comparable)
        jdir = C.OUT / "ds_jsondet"
        outs = []
        for _ in range(2):
            _clean(jdir)
            r = run_cli(["init", "--dataset", str(jdir),
                         "--observation", str(C.OBS_IN), "--json"])
            outs.append(r)
        _clean(jdir)
        C.record("json_determinism",
                 same=outs[0]["stdout"] == outs[1]["stdout"],
                 exit=outs[0]["exit"],
                 parseable=_is_json(outs[0]["stdout"]))

        # ---- B11: injected mid-bootstrap failures
        for hook in ("during_table:facts", "before_publish"):
            with tempfile.TemporaryDirectory() as td:
                dest = Path(td) / "ds"
                try:
                    uboot.init_dataset(dest, obs_doc, fail_hook=hook)
                    C.record(f"inject_{hook}", raised=False)
                except RuntimeError:
                    staging = list(Path(td).glob("*.staging-init"))
                    C.record(f"inject_{hook}", raised=True,
                             dest_exists=dest.exists(),
                             staging_left=len(staging))

    # ---- B3: PYTHONHASHSEED reruns (subprocesses — the in-process run
    # already used this interpreter's seed)
    if rebuild:
        env0 = dict(os.environ, PYTHONHASHSEED="0",
                    PYTHONPATH=str(REPO / "src"))
        env777 = dict(env0, PYTHONHASHSEED="777")
        for env, dest, tag in ((env0, C.DS_S0, "seed0"),
                               (env777, C.DS_S777, "seed777")):
            r = subprocess.run(
                [sys.executable, "-m", "opencnmv", "init",
                 "--dataset", str(dest), "--observation", str(C.OBS_IN)],
                cwd=REPO, env=env, capture_output=True, text=True)
            C.record(f"init_{tag}", exit=r.returncode,
                     stdout=r.stdout[-400:], stderr=r.stderr[-400:])
        C.record("seed_equal",
                 s0_vs_777=C.dir_hashes(C.DS_S0)
                 == C.dir_hashes(C.DS_S777),
                 s0_vs_obs=C.dir_hashes(C.DS_S0) == hashes_obs)

    # ---- B5: no gate imports in production code (module scan, same
    # mechanism as G2-A A3, extended to g2/)
    bad = []
    for p in (REPO / "src").rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8")
                                 .splitlines(), 1):
            if re.match(r"\s*(from|import)\s+(g0_r|g0-r|g1|g2)[\.\s]",
                        line):
                bad.append(f"{p.name}:{i}:{line.strip()}")
    C.record("gate_imports", bad=bad)

    # ---- B6: extras_json absent yet valid (validate already ran);
    # count non-null extras_json in the bootstrapped filing table
    import duckdb  # noqa: E402
    n_extras = duckdb.sql(
        f"select count(*) from read_parquet("
        f"'{C.DS_OBS.as_posix()}/filing.parquet') "
        f"where extras_json is not null").fetchone()[0]
    C.record("extras_absent", nonnull_extras=n_extras)

    # ---- B7: bounded live smoke + offline replay of its evidence
    if not args.offline:
        _clean(C.DS_LIVE)
        _clean(C.DS_LIVE_REPLAY)
        _clean(C.EV_LIVE)
        r = run_cli(["init", "--dataset", str(C.DS_LIVE), "--live",
                     "--evidence-dir", str(C.EV_LIVE),
                     "--taxonomy-dir", str(C.TAX_DIR),
                     "--issuer", "A-48010615", "--family", "ipp",
                     "--min-delay", str(C.MIN_DELAY)])
        C.record("init_live", **r)
        live_hashes = C.dir_hashes(C.DS_LIVE) if C.DS_LIVE.is_dir() \
            else {}
        m = re.search(r"capture_id: (\S+)", r["stdout"])
        C.record("init_live_capture_id",
                 capture_id=m.group(1) if m else None,
                 artifacts=len(list((C.EV_LIVE / "artifacts").iterdir()))
                 if (C.EV_LIVE / "artifacts").is_dir() else 0,
                 runs=(C.EV_LIVE / "runs").is_dir())
        # replay: same evidence dir + taxonomy, offline -> identical ds
        with deny_network():
            r2 = run_cli(["init", "--dataset", str(C.DS_LIVE_REPLAY),
                          "--evidence-dir", str(C.EV_LIVE),
                          "--taxonomy-dir", str(C.TAX_DIR)])
            C.record("init_live_replay", **r2)
            C.record("live_replay_equal",
                     ok=C.dir_hashes(C.DS_LIVE_REPLAY) == live_hashes
                     and bool(live_hashes))

    # ---- B8: every G2-E read-only command on the bootstrapped
    # dataset — ids resolved dynamically from the dataset itself
    ds = C.DS_OBS.as_posix()

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
    h2_state = q(f"select state_id from read_parquet('{ds}/facts.parquet')"
                 " where state_id like '%-H2-%' limit 1")[0][0]
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
        ("filings.issuer",
         ["--dataset", ds, "filings", "--issuer", "iberdrola",
          "--json"]),
        ("filing.esef", ["--dataset", ds, "filing", esef_id, "--json"]),
        ("filing.ipp", ["--dataset", ds, "filing", ipp_id, "--json"]),
        ("history", ["--dataset", ds, "history", esef_id, "--json"]),
        ("history.variant",
         ["--dataset", ds, "history", variant, "--json"]),
        ("facts.state",
         ["--dataset", ds, "facts", "--state", state_id, "--limit",
          "5"]),
        ("facts.count", ["--dataset", ds, "facts", "--count"]),
        ("facts.h2dims",
         ["--dataset", ds, "facts", "--state", h2_state,
          "--limit", "5", "--jsonl"]),
        ("fact", ["--dataset", ds, "fact", fact_id, "--json"]),
        ("compare", ["--dataset", ds, "compare", esef_id, "--json"]),
        ("events.all", ["--dataset", ds, "events", "--jsonl"]),
        ("events.filing", ["--dataset", ds, "events", esef_id]),
        ("mappings", ["--dataset", ds, "mappings", esef_id, "--json"]),
        ("mappings.verdict",
         ["--dataset", ds, "mappings", esef_id, "--verdict",
          "AMBIGUOUS", "--json"]),
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
        ("err.unknown_fact",
         ["--dataset", ds, "fact", "fact:nope"]),
        ("err.missing_dataset",
         ["--dataset", str(C.OUT / "nonexistent"), "dataset", "info"]),
        ("err.usage",
         ["--dataset", ds, "filings", "--bogus-flag"]),
    ]
    before = C.dir_hashes(C.DS_OBS)
    with deny_network():
        for name, argv in read_cmds:
            r = run_cli(argv)
            C.record(f"read.{name}", **r)
    C.record("read_bytes_unchanged",
             ok=C.dir_hashes(C.DS_OBS) == before)

    # ---- B9: update with the same observation -> NO_CHANGE, zero
    # bytes changed (bootstrap is the update fixpoint)
    with deny_network():
        r = run_cli(["update", "--dataset", str(C.DS_OBS),
                     "--observation", str(C.OBS_IN)])
        C.record("update_fixpoint", **r)
        C.record("fixpoint_bytes_unchanged",
                 ok=C.dir_hashes(C.DS_OBS) == before)

    # ---- B12: no absolute paths in manifest/provenance
    man_text = (C.DS_OBS / "dataset_manifest.json").read_text(
        encoding="utf-8")
    abs_in_man = bool(re.search(r"[A-Za-z]:[\\/]|/(home|Users|tmp)/",
                                man_text))
    prov = duckdb.sql(
        f"select evidence_path, sha256 from read_parquet("
        f"'{ds}/provenance.parquet')").fetchall()
    prov_ok = all(p and not Path(p).is_absolute() and ":" not in p
                  and s for p, s in prov)
    C.record("no_abs_paths", manifest_clean=not abs_in_man,
             prov_rows=len(prov), prov_relative=prov_ok)

    # ---- B13: semantic parity vs the frozen G2-C dataset, per
    # filing (the bootstrapped set is the 21-filing corpus — the G2-C
    # fixture additionally carries the TEF lifecycle fixture filing,
    # outside the frozen issuer universe). Same documented exclusions
    # as G2-F F7.
    from opencnmv.update import apply as uapply
    from opencnmv.update.classify import filing_scoped_rows
    tables_g2c = uapply.load_tables(C.G2C_DS)
    tables_new = uapply.load_tables(C.DS_OBS)
    EXCLUDE = {"provenance": {"retrieved_at", "resolved_url",
                              "evidence_path", "source_url",
                              "http_status"},
               "artifact": {"source_url"},
               "filing": {"extras_json"}}

    def _norm(t: str, r: dict) -> dict:
        r = {k: v for k, v in r.items() if k not in EXCLUDE.get(t, ())}
        if t == "extension_mapping" and r.get("record_json"):
            rec = json.loads(r["record_json"])
            rec.pop("filing", None)
            r["record_json"] = json.dumps(rec, sort_keys=True,
                                          ensure_ascii=False)
        return r

    report = {}
    for f in obs_doc["filings"]:
        fid = f["filing"]["filing_id"]
        per = {}
        left = filing_scoped_rows(tables_new, fid)
        right = filing_scoped_rows(tables_g2c, fid)
        for t in left:
            def enc(rs):
                return sorted(json.dumps(x, sort_keys=True,
                                         ensure_ascii=False,
                                         default=str) for x in rs)
            per[t] = {"new": len(left[t]), "g2c": len(right[t]),
                      "equal": enc([_norm(t, x) for x in left[t]])
                      == enc([_norm(t, x) for x in right[t]])}
        report[fid] = per
    C.jwrite(C.OUT / "semantics_compare.json", report)
    fams = {"ESEF_IFA": 0, "IPP": 0}
    for f in obs_doc["filings"]:
        fams[f["filing"]["family"]] += 1
    n_ev = duckdb.sql(f"select count(*) from read_parquet("
                      f"'{ds}/version_event.parquet')").fetchone()[0]
    n_map = duckdb.sql(f"select count(*) from read_parquet("
                       f"'{ds}/extension_mapping.parquet')").fetchone()[0]
    ibe_variants = duckdb.sql(
        f"select variant_id from read_parquet("
        f"'{ds}/submission_variant.parquet') where variant_id like "
        f"'cnmv:ifa:20515%' or variant_id like 'cnmv:ifa:20934%'").fetchall()
    C.record("semantics",
             filings=len(report),
             all_equal=all(t["equal"] for f in report.values()
                           for t in f.values()),
             esef=fams["ESEF_IFA"], ipp=fams["IPP"],
             version_events=n_ev, extension_mappings=n_map,
             ibe_variants=[v[0] for v in ibe_variants])

    # ---- corpus hash determinism across all bootstrap products
    mans = {}
    for tag, d in (("obs", C.DS_OBS), ("ev", C.DS_EV),
                   ("s0", C.DS_S0), ("s777", C.DS_S777)):
        m = C.jload(d / "dataset_manifest.json")
        mans[tag] = m["corpus_logical_sha256"]
    C.record("corpus_hashes", **mans,
             all_equal=len(set(mans.values())) == 1)

    print("g2g_run complete ->", C.RESULTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
