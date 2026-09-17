"""G2-F run step: live capture + offline update legs over the frozen
SAN/BBVA/IBE corpus.

    python g2f_run.py             # all legs (live network in observe)
    python g2f_run.py --offline   # skip live legs, reuse _out evidence

Produces under _out/:
    dataset/            working copy of the G2-C runA dataset
    evidence/liveA/     full-corpus live capture (one session, min delay)
    evidence/liveB/     representative recapture (SAN+IBE, both families)
    obsA.json           assembled observation (liveA, rebased on dataset)
    obs_bootstrap.json  bootstrap observation (no base tables; F7 oracle)
    results.jsonl       per-leg result lines for g2f_verify.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
import tempfile
import time
import unittest.mock as mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import g2f_common as C  # noqa: E402

from opencnmv.capture import observe as cobs  # noqa: E402
from opencnmv.capture.contract import CaptureError  # noqa: E402
from opencnmv.capture.fetch import PoliteSession  # noqa: E402
from opencnmv.cli.main import entry as cli_entry  # noqa: E402
from opencnmv.dataset import manifest as dmanifest  # noqa: E402
from opencnmv.dataset import parquetio, schema as dschema  # noqa: E402
from opencnmv.update import apply as uapply  # noqa: E402
from opencnmv.update import delta as udelta  # noqa: E402
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
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = cli_entry(argv)
    return {"argv": argv, "exit": code, "stdout": out.getvalue(),
            "stderr": err.getvalue()}


def leg_live_observe(ev_dir: Path, out: Path | None, issuers=None,
                     families=None, delay=C.MIN_DELAY) -> dict:
    t0 = time.time()
    res = cobs.observe(
        evidence_dir=ev_dir, out=out,
        issuer_nifs=issuers, families=families, min_delay=delay,
        dataset_dir=C.DS if C.DS.is_dir() else None,
        tax_dir=C.TAX_DIR)
    res["elapsed_s"] = round(time.time() - t0, 1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="reuse existing evidence dirs (no network)")
    args = ap.parse_args()

    C.OUT.mkdir(parents=True, exist_ok=True)
    # --offline appends over the previous run's records: live legs are
    # not re-executed, so their evidence lines must survive; the
    # verifier resolves duplicate names to the last occurrence, which
    # keeps re-executed offline legs current.
    if C.RESULTS.exists() and not args.offline:
        C.RESULTS.unlink()

    # ---- fixture: working copy of the frozen G2-C runA dataset
    if not args.offline or not C.DS.is_dir():
        if C.DS.exists():
            shutil.rmtree(C.DS)
        shutil.copytree(C.G2C_DS, C.DS)
    base_hashes = C.dir_hashes(C.DS)
    C.jwrite(C.OUT / "dataset_hashes_base.json", base_hashes)
    man = uapply.load_manifest(C.DS)
    base_corpus = man["corpus_logical_sha256"]

    # ---- live leg A: full frozen-corpus capture + observation
    run_a = None
    if not args.offline:
        res = leg_live_observe(C.EV_A, C.OUT / "obsA_observe.json")
        C.jwrite(C.OUT / "observeA_result.json", res)
        C.record("observeA", **res)
    # pin the full-corpus run explicitly (a later dedup probe adds a
    # second run to the same store — 'latest' would silently shift)
    run_a = C.jload(C.OUT / "observeA_result.json")["capture_id"]

    # obsA is always re-assembled offline from the preserved evidence —
    # this is also the determinism check vs the live-written document.
    obs_a = cobs.assemble_from_evidence(
        C.EV_A, dataset_dir=C.DS, tax_dir=C.TAX_DIR,
        work_dir=C.OUT / "work_a", run=run_a)
    C.jwrite(C.OBS_A, obs_a)
    obs_live = C.OUT / "obsA_observe.json"
    if obs_live.is_file():
        live_doc = uobs.load(obs_live)
        C.record("assemble_deterministic",
                 equal=uobs.observation_sha256(obs_a)
                 == uobs.observation_sha256(live_doc))
    C.record("obsA_sha256", sha=obs_a["observation_sha256"],
             filings=len(obs_a["filings"]))

    # ---- offline legs over liveA evidence
    with deny_network():
        # F3/F4: update --observation --dry-run (zero network, zero writes)
        before = C.dir_hashes(C.DS)
        r = run_cli(["update", "--dataset", str(C.DS),
                     "--observation", str(C.OBS_A), "--dry-run"])
        C.record("update_dryrun", **r)
        C.record("dryrun_bytes_unchanged",
                 ok=before == C.dir_hashes(C.DS))

        # F6: apply
        r = run_cli(["update", "--dataset", str(C.DS),
                     "--observation", str(C.OBS_A)])
        C.record("update_apply", **r)

        # F5: second identical apply -> NO_CHANGE, byte-identical
        r = run_cli(["update", "--dataset", str(C.DS),
                     "--observation", str(C.OBS_A)])
        C.record("update_apply_2", **r)
        C.record("apply_bytes_unchanged",
                 ok=before == C.dir_hashes(C.DS))

        # dataset validate post-apply
        r = run_cli(["dataset", "validate", "--dataset", str(C.DS)])
        C.record("dataset_validate", **r)

    # ---- F7 oracle: bootstrap observation (no base tables) -> clean
    # rebuild of the scoped state; compare per-filing scoped rows vs the
    # incremental result (the dataset itself when delta is NO_CHANGE).
    tables_ds = uapply.load_tables(C.DS)
    if args.offline and C.OBS_BOOT.is_file():
        obs_boot = uobs.load(C.OBS_BOOT)
    else:
        obs_boot = cobs.assemble_from_evidence(
            C.EV_A, dataset_dir=None, tax_dir=C.TAX_DIR,
            work_dir=C.OUT / "work_boot")
        C.jwrite(C.OBS_BOOT, obs_boot)
    empty = {t: [] for t in tables_ds}
    d_boot = udelta.plan(empty, obs_boot, base_corpus_logical_sha256="0" * 64)
    merged = udelta.merged_tables(empty, {
        "added": d_boot["rows_added"], "updated": d_boot["rows_updated"],
        "removed": d_boot["rows_removed"]})
    from opencnmv.update.classify import filing_scoped_rows
    # per-observation retrieval metadata + curated fixture overlays —
    # documented exclusions (retrieval fields legitimately differ between
    # the G2-C fixture observation and the liveA capture):
    EXCLUDE = {"provenance": {"retrieved_at", "resolved_url",
                              "evidence_path", "source_url",
                              "http_status"},
               "artifact": {"source_url"},
               "filing": {"extras_json"}}

    def _norm(t: str, r: dict) -> dict:
        r = {k: v for k, v in r.items() if k not in EXCLUDE.get(t, ())}
        if t == "extension_mapping" and r.get("record_json"):
            rec = json.loads(r["record_json"])
            rec.pop("filing", None)   # fixture label vs canonical id
            r["record_json"] = json.dumps(rec, sort_keys=True,
                                          ensure_ascii=False)
        return r

    f7_report = {}
    for f in obs_a["filings"]:
        fid = f["filing"]["filing_id"]
        left = filing_scoped_rows(merged, fid)
        right = filing_scoped_rows(tables_ds, fid)
        per = {}
        for t in left:
            lrows = [_norm(t, r) for r in left[t]]
            rrows = [_norm(t, r) for r in right[t]]

            def enc(rs):
                return sorted(json.dumps(r, sort_keys=True,
                                         ensure_ascii=False,
                                         default=str)
                              for r in rs)
            per[t] = {"merged": len(lrows), "dataset": len(rrows),
                      "equal": enc(lrows) == enc(rrows)}
        f7_report[fid] = per
    C.jwrite(C.OUT / "f7_compare.json", f7_report)
    C.record("f7_oracle",
             filings=len(f7_report),
             all_equal=all(t["equal"] for f in f7_report.values()
                           for t in f.values()))

    # ---- representative recapture (F2/F14): SAN+IBE, both families
    if not args.offline:
        res = leg_live_observe(C.EV_B, None,
                               issuers=["A39000013", "A-48010615"],
                               delay=C.MIN_DELAY)
        C.jwrite(C.OUT / "observeB_result.json", res)
        C.record("observeB", **res)
        # obsB assembled offline against the same base dataset
        obs_b_doc = cobs.assemble_from_evidence(
            C.EV_B, dataset_dir=C.DS, tax_dir=C.TAX_DIR,
            work_dir=C.OUT / "work_b", run=res["capture_id"])
        C.jwrite(C.OBS_B, obs_b_doc)
        # same-dir dedup probe: re-run IBE/IPP into liveA
        n_before = len(list((C.EV_A / "artifacts").iterdir()))
        res = leg_live_observe(C.EV_A, None,
                               issuers=["A-48010615"], families=["ipp"],
                               delay=C.MIN_DELAY)
        n_after = len(list((C.EV_A / "artifacts").iterdir()))
        C.record("dedup_probe", artifacts_before=n_before,
                 artifacts_after=n_after, fetches=res["fetches"],
                 capture_id=res["capture_id"])

    # ---- failure legs (offline, in-process)
    # F9: mid-capture network failure -> CaptureError, no manifest run
    class FailAfterN(PoliteSession):
        def __init__(self, n, **kw):
            super().__init__(**kw)
            self._n = n
            self._calls = 0

        def get(self, url, **kw):
            self._calls += 1
            if self._calls > self._n:
                raise CaptureError("injected mid-capture failure")
            return super().get(url, **kw)

    ev_fail = C.OUT / "evidence" / "liveFail"
    if not args.offline:
        ds_before = C.dir_hashes(C.DS)
        try:
            cobs.observe(evidence_dir=ev_fail, out=None,
                         issuer_nifs=["A-48010615"], families=["ipp"],
                         min_delay=C.MIN_DELAY,
                         session=FailAfterN(3, min_delay=C.MIN_DELAY))
            C.record("capture_failure", raised=False)
        except CaptureError as e:
            C.record("capture_failure", raised=True, error=str(e)[:200],
                     dataset_unchanged=ds_before == C.dir_hashes(C.DS),
                     runs_exist=(ev_fail / "runs").is_dir()
                     and any((ev_fail / "runs").iterdir()))

    # F10: stale base — plan against dataset, then apply to a copy whose
    # manifest hash was tampered
    with deny_network():
        tables = uapply.load_tables(C.DS)
        d = udelta.plan(tables, obs_a, base_corpus)
        with tempfile.TemporaryDirectory() as td:
            stale_ds = Path(td) / "ds"
            shutil.copytree(C.DS, stale_ds)
            mp = stale_ds / "dataset_manifest.json"
            m = json.loads(mp.read_text(encoding="utf-8"))
            m["corpus_logical_sha256"] = "0" * 64
            mp.write_text(json.dumps(m), encoding="utf-8")
            try:
                uapply.apply_delta(stale_ds, d)
                C.record("stale_base", raised=False)
            except uapply.StaleBaseError as e:
                C.record("stale_base", raised=True, error=str(e)[:160])

        # F11: tampered observation
        obs_t = dict(obs_a)
        obs_t["filings"] = json.loads(json.dumps(obs_a["filings"]))
        obs_t["filings"][0]["filing"]["period_end"] = "01/01/1999"
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "obs.json"
            p.write_text(json.dumps(obs_t), encoding="utf-8")
            r = run_cli(["update", "--dataset", str(C.DS),
                         "--observation", str(p)])
            C.record("tampered_obs", **r)

        # F12: injected apply failure -> no partial publish. Needs a
        # delta with real row ops: the bootstrap delta (all rows added)
        # applied onto a valid empty-base dataset.
        empty_ds = C.OUT / "empty_ds"
        if not (empty_ds / "dataset_manifest.json").is_file():
            empty_ds.mkdir(parents=True, exist_ok=True)
            meta = {t: parquetio.write_table(t, [], empty_ds / f"{t}.parquet")
                    for t in dschema.TABLE_ORDER}
            em = dmanifest.build_manifest(
                inputs={"base": {"corpus_logical_sha256": "0" * 64}},
                tables=meta, code_commit="g2f",
                generator={"name": "g2f_run"}, params={})
            em["corpus_logical_sha256"] = "0" * 64
            (empty_ds / "dataset_manifest.json").write_text(
                json.dumps(em, indent=1, sort_keys=True), encoding="utf-8")
            (empty_ds / "schema").mkdir(exist_ok=True)
            for t in dschema.TABLE_ORDER:
                (empty_ds / "schema" / f"{t}.schema.json").write_bytes(
                    json.dumps(dschema.schema_dict(t), indent=1)
                    .encode("utf-8"))
        with tempfile.TemporaryDirectory() as td:
            inj_ds = Path(td) / "ds"
            shutil.copytree(empty_ds, inj_ds)
            try:
                uapply.apply_delta(inj_ds, d_boot,
                                   fail_hook="during_table:facts")
                C.record("apply_inject", raised=False)
            except RuntimeError as e:
                leftovers = list(inj_ds.parent.glob("*.staging-*"))
                C.record("apply_inject", raised=True, error=str(e)[:160],
                         dataset_intact=(inj_ds / "dataset_manifest.json")
                         .is_file(),
                         staging_left=len(leftovers))

        # F13: unresolved — observation conflicting on period_end
        obs_c = json.loads(json.dumps(obs_a))
        for f in obs_c["filings"]:
            if f["filing"]["filing_id"] == "cnmv:ipp:2024098684":
                f["filing"]["period_end"] = "2024-06-29"
        del obs_c["observation_sha256"]
        obs_c["observation_sha256"] = uobs.observation_sha256(obs_c)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "obs_conflict.json"
            p.write_text(json.dumps(obs_c), encoding="utf-8")
            r = run_cli(["update", "--dataset", str(C.DS),
                         "--observation", str(p), "--dry-run"])
            C.record("unresolved_preview", **r)
            r = run_cli(["update", "--dataset", str(C.DS),
                         "--observation", str(p), "--fail-on-unresolved"])
            C.record("unresolved_fail", **r)
            C.record("unresolved_bytes_unchanged",
                     ok=before == C.dir_hashes(C.DS))

        # F8: issuer outside frozen corpus -> exit 7, no network
        r = run_cli(["observe", "--evidence-dir",
                     str(C.OUT / "evidence" / "liveX"),
                     "--issuer", "X99999999"])
        C.record("bad_issuer", **r)

        # F19: deterministic output — same dry-run twice
        r1 = run_cli(["update", "--dataset", str(C.DS),
                      "--observation", str(C.OBS_A), "--dry-run"])
        r2 = run_cli(["update", "--dataset", str(C.DS),
                      "--observation", str(C.OBS_A), "--dry-run"])
        r3 = run_cli(["update", "--dataset", str(C.DS),
                      "--observation", str(C.OBS_A), "--dry-run",
                      "--json"])
        C.record("determinism", same_stdout=r1["stdout"] == r2["stdout"],
                 same_stderr=r1["stderr"] == r2["stderr"],
                 json_exit=r3["exit"],
                 json_parseable=_is_json(r3["stdout"]))

        # F16: issuer-scoped observation (liveB if present, else
        # filtered obsA) must not emit removals for unobserved filings
        obs_b_path = C.OBS_B if C.OBS_B.is_file() else None
        if obs_b_path:
            obs_b = uobs.load(obs_b_path)
        else:
            obs_b = {"observation_format": obs_a["observation_format"],
                     "observation_id": obs_a["observation_id"] + "-sub",
                     "captured_at": obs_a["captured_at"],
                     "filings": [f for f in obs_a["filings"]
                                 if f["filing"]["issuer"].get("lei")
                                 != "K8MS7FD7N5Z2WQ51AZ71"]}
            obs_b["observation_sha256"] = uobs.observation_sha256(obs_b)
        d_sub = udelta.plan(tables, obs_b, base_corpus)
        C.record("partial_scope",
                 n_transitions=len(d_sub["transitions"]),
                 removed_rows={t: len(d_sub["rows_removed"][t])
                               for t in d_sub["rows_removed"]
                               if d_sub["rows_removed"][t]},
                 filings=[f["filing"]["filing_id"]
                          for f in obs_b["filings"]])

    print("g2f_run complete ->", C.RESULTS)
    return 0


def _is_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
