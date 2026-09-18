"""Tests for opencnmv.capture + the observe/update CLI surface.

No network anywhere: discovery parsers run on synthetic HTML, the
polite session is exercised against a stubbed requests.Session, and
assembly runs against a tiny inline COLUMNAR_DATASET_V1 whose artifact
hashes the synthetic capture manifest mirrors (the "CNMV unchanged"
case -> all NO_CHANGE, zero row ops).
"""
from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from opencnmv.capture import assemble as casm
from opencnmv.capture import contract as C
from opencnmv.capture import discover as cdis
from opencnmv.capture import fetch as cfetch
from opencnmv.capture import observe as cobs
from opencnmv.cli.main import entry
from opencnmv.dataset import manifest as dmanifest
from opencnmv.dataset import parquetio, schema as dschema, tables
from opencnmv.provenance.hashes import artifact_set_id, sha256_bytes
from opencnmv.update import apply as uapply
from opencnmv.update import delta as udelta
from opencnmv.update import observe as uobs

PKG_ES = "aa" * 32
PKG_EN = "bb" * 32
IPP_BIN = "cc" * 32


def _zip(lang: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"LEI-20241231-{lang}/x.xhtml", "<html/>")
    return buf.getvalue()


def _filing_ibe() -> dict:
    """Single-variant filing with an en->es fallback view (IBE shape)."""
    fid = "cnmv:ifa:90001"
    return {
        "filing_id": fid,
        "issuer": {"denomination": "IBERDROLA, S.A.",
                   "lei": "5QK37QC7NWOJ8D7WVQ45"},
        "registro_oficial": "90001", "family": "ESEF_IFA",
        "period_end": "31/12/2024",
        "filing_versions": [{
            "filing_version_id": f"{fid}#nreg:20250001",
            "source_nreg": "20250001", "filed_at": None,
            "submission_kind": "ORIGINAL_SUBMISSION"}],
        "submission_variants": [{
            "variant_id": f"{fid}#es", "filing_id": fid,
            "submission_language": "es",
            "variant_versions": [{
                "variant_version_id": f"{fid}#es#v1",
                "variant_id": f"{fid}#es", "observed": True,
                "artifact_set_id": artifact_set_id(
                    [{"role": "ESEF_PACKAGE_ZIP_XBRL",
                      "sha256": PKG_ES}]),
                "artifacts": [{
                    "artifact_id": f"sha256:{PKG_ES}",
                    "role": "ESEF_PACKAGE_ZIP_XBRL", "sha256": PKG_ES,
                    "bytes": 100, "media_type": "application/zip",
                    "package_lang_tag": "es"}],
                "created_by_event_id": f"{fid}#evt:formulacion",
                "supersedes_variant_version_id": None}]}],
        "view_resolutions": [
            {"requested_ui_language": "es",
             "resolved_variant_id": f"{fid}#es",
             "resolution_mode": "SUBMITTED_VARIANT"},
            {"requested_ui_language": "en",
             "resolved_variant_id": f"{fid}#es",
             "resolution_mode": "FALLBACK_TO_ES"}],
        "version_events": [{
            "event_id": f"{fid}#evt:formulacion", "event_date":
                "14/02/2025",
            "event_type": "CERTIFICATE",
            "source_label": "formulación y firma",
            "source_nreg": "20250001", "evidence_artifact_id": None,
            "scope_status": "NOT_A_VERSION_TRANSITION", "affects": []}],
        "extension_mappings": []}


def _filing_ipp() -> dict:
    fid = "cnmv:ipp:2025000001"
    return {
        "filing_id": fid,
        "issuer": {"denomination": "IBERDROLA, S.A.",
                   "nif": "A-48010615",
                   "lei": "5QK37QC7NWOJ8D7WVQ45"},
        "registro_oficial": "2025000001", "family": "IPP",
        "period_end": "2025-06-30",
        "filing_versions": [{
            "filing_version_id": f"{fid}#nreg:2025000001",
            "source_nreg": "2025000001", "filed_at": "2025-07-30",
            "submission_kind": "ORIGINAL_SUBMISSION",
            "artifacts": [{
                "artifact_id": f"sha256:{IPP_BIN}", "role": "IPP_XBRL",
                "sha256": IPP_BIN, "bytes": 50, "media_type": "text/xml",
                "source_url": "https://www.cnmv.es/dl",
                "package_lang_tag": "es"}]}],
        "submission_variants": [{
            "variant_id": f"{fid}#es", "filing_id": fid,
            "submission_language": "es",
            "variant_versions": [{
                "variant_version_id": f"{fid}#es#v1",
                "variant_id": f"{fid}#es", "observed": True,
                "artifact_set_id": artifact_set_id(
                    [{"role": "IPP_XBRL", "sha256": IPP_BIN}]),
                "artifacts": [],
                "created_by_event_id": None,
                "supersedes_variant_version_id": None}]}],
        "view_resolutions": [{
            "requested_ui_language": "es",
            "resolved_variant_id": f"{fid}#es",
            "resolution_mode": "SUBMITTED_VARIANT"}],
        "version_events": [], "extension_mappings": []}


def build_ds(dest: Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    tbl: dict[str, list[dict]] = {t: [] for t in dschema.TABLE_ORDER}
    for fx in (_filing_ibe(), _filing_ipp()):
        rows = tables.filing_rows(fx)
        for t, rl in rows.items():
            tbl[t].extend(rl)
    meta = {}
    for t in dschema.TABLE_ORDER:
        meta[t] = parquetio.write_table(
            t, sorted(tbl[t], key=parquetio.ROW_ORDER[t]),
            dest / f"{t}.parquet")
    man = dmanifest.build_manifest(
        inputs={"fixture": {"path": "tests/test_capture.py",
                            "sha256": "0" * 64}},
        tables=meta, code_commit="test", generator={"name": "test"},
        params={})
    (dest / "dataset_manifest.json").write_text(
        json.dumps(man, indent=1, sort_keys=True), encoding="utf-8")
    (dest / "schema").mkdir(exist_ok=True)
    for t in dschema.TABLE_ORDER:
        (dest / "schema" / f"{t}.schema.json").write_bytes(
            json.dumps(dschema.schema_dict(t), indent=1,
                       ensure_ascii=False).encode("utf-8"))
    return dest


def synthetic_manifest() -> dict:
    """Capture manifest mirroring the mini dataset — 'CNMV unchanged'."""
    link = ("infadicionifa.aspx?id=0&lang=es&nreg=20250001"
            "&nregaud=90001")
    views = []
    for lang, mode, resolved, sha in (
            ("es", "SUBMITTED_VARIANT", "es", PKG_ES),
            ("en", "FALLBACK_TO_ES", "es", PKG_ES)):
        views.append({
            "issuer_key": "IBE", "nif": "A-48010615",
            "registro": "90001", "requested_ui_language": lang,
            "registry_row": {
                "cells": ["90001", "31/12/2024", "14/02/2025"],
                "tokens": ["t1", "t2", "t3"], "infadicion": [link]},
            "search_page": {"sha256": "0" * 64,
                            "evidence_path": "artifacts/p.html"},
            "document_locators": {},
            "package": {"sha256": sha, "byte_size": 100,
                        "media_type": "application/zip",
                        "evidence_path": "artifacts/pkg.zip",
                        "source_url": "https://www.cnmv.es/ver?e=t3"},
            "resolved_submission_language": resolved,
            "resolution_mode": mode,
            "variant_artifact_set_id": artifact_set_id(
                [{"role": "ESEF_PACKAGE_ZIP_XBRL", "sha256": sha}])})
    return {
        "capture_manifest": "CNMV_CAPTURE_V1",
        "capture_id": "cap-test", "captured_at": "2026-09-17T00:00:00Z",
        "user_agent": "test-agent", "min_delay_s": 0.0,
        "scope": {}, "fetch_log": [],
        "esef_views": views,
        "ipp_filings": [{
            "issuer_key": "IBE", "nif": "A-48010615", "slot": "H1-2025",
            "semester": "I", "year": 2025, "period_end": "2025-06-30",
            "listaifi_page": {}, "nreg": "2025000001",
            "published": "30/07/2025", "detail_page": {},
            "download_guid": "g",
            "artifact": {"sha256": IPP_BIN, "byte_size": 50,
                         "media_type": "text/xml",
                         "evidence_path": "artifacts/i.xbrl",
                         "source_url": "https://www.cnmv.es/dl",
                         "artifact_id": f"sha256:{IPP_BIN}"},
            "status": "CAPTURED"}],
        "infadicion_walks": [{"issuer_key": "IBE", "registro": "90001",
                              "nreg": "20250001", "nregaud": "90001",
                              "page": {}, "events": []}],
        "warnings": []}


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = entry(argv)
    return code, out.getvalue(), err.getvalue()


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


# ---------------------------------------------------------------- unit

class TestStore(unittest.TestCase):
    def test_write_once_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            st = cfetch.EvidenceStore(Path(td))
            rel1, sha1, stored1 = st.store(b"hello", media_type=None)
            rel2, sha2, stored2 = st.store(b"hello", media_type=None)
            self.assertTrue(stored1)
            self.assertFalse(stored2)            # identical -> dedup
            self.assertEqual(rel1, rel2)
            rel3, sha3, stored3 = st.store(b"HELLO", media_type=None)
            self.assertTrue(stored3)             # different bytes -> own sha
            self.assertNotEqual(rel1, rel3)
            self.assertNotEqual(sha1, sha3)

    def test_corrupt_object_detected(self):
        with tempfile.TemporaryDirectory() as td:
            st = cfetch.EvidenceStore(Path(td))
            rel, sha, _ = st.store(b"data")
            (Path(td) / rel).write_bytes(b"tampered")
            with self.assertRaises(C.CaptureError):
                st.store(b"data")


class TestPoliteSession(unittest.TestCase):
    def _resp(self, status=200, body=b"x", ctype="text/plain"):
        r = mock.Mock()
        r.status_code = status
        r.content = body
        r.url = "http://example/x"
        r.headers = {"Content-Type": ctype}
        r.text = body.decode("utf-8", "replace")
        return r

    def test_delay_and_log(self):
        s = cfetch.PoliteSession(min_delay=5.0)
        self.assertEqual(
            s.session.headers["User-Agent"], C.USER_AGENT)
        s.session = mock.Mock()
        s.session.get.return_value = self._resp()
        s.session.headers = {}
        with mock.patch("opencnmv.capture.fetch.time.sleep") as slp:
            s.get("http://example/a")
            s.get("http://example/b")
        self.assertEqual(slp.call_count, 1)      # delay between requests
        self.assertGreater(slp.call_args[0][0], 0)
        self.assertEqual(len(s.fetch_log), 2)
        self.assertEqual(s.fetch_log[0]["http_status"], 200)

    def test_non_200_is_capture_error(self):
        s = cfetch.PoliteSession(min_delay=0)
        s.session = mock.Mock()
        s.session.headers = {}
        s.session.get.return_value = self._resp(status=404)
        with self.assertRaises(C.CaptureError):
            s.get("http://example/x")

    def test_transport_error_is_capture_error(self):
        import requests
        s = cfetch.PoliteSession(min_delay=0)
        s.session = mock.Mock()
        s.session.headers = {}
        s.session.get.side_effect = requests.ConnectionError("down")
        with self.assertRaises(C.CaptureError):
            s.get("http://example/x")


class TestDiscoveryHelpers(unittest.TestCase):
    def test_ipp_slot_regex(self):
        for text, want in (("I semestre de 2024", ("I", 2024)),
                           ("II semestre de 2025", ("II", 2025)),
                           ("informe anual 2024", None)):
            m = cdis._IPP_SLOT_RE.search(text)
            self.assertEqual(
                (m.group(1).upper(), int(m.group(2))) if m else None,
                want)

    def test_lang_tags(self):
        self.assertEqual(cdis._lang_tags(_zip("es")), {"es"})
        self.assertEqual(cdis._lang_tags(_zip("en")), {"en"})
        with self.assertRaises(C.CaptureError):
            cdis._lang_tags(b"not a zip")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("LEI-20241231-es/a.xhtml", "x")
            z.writestr("LEI-20241231-en/b.xhtml", "x")
        self.assertEqual(cdis._lang_tags(buf.getvalue()), {"es", "en"})

    def test_scope_rejects_unknown(self):
        with self.assertRaises(C.CaptureError):
            cobs.resolve_scope(["X99999999"], None)
        with self.assertRaises(C.CaptureError):
            cobs.resolve_scope(None, ["oir"])
        nifs, fams = cobs.resolve_scope(["A39000013"], ["ipp"])
        self.assertEqual(nifs, ["A39000013"])
        self.assertEqual(fams, {"ipp"})


class TestAssemble(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ds = build_ds(Path(self._tmp.name) / "ds")
        self.tables = uapply.load_tables(self.ds)
        self.manifest = synthetic_manifest()

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_change_roundtrip(self):
        obs = casm.assemble_observation(
            self.manifest, tables=self.tables,
            evidence_root=Path(self._tmp.name))
        uobs.verify_self_consistency(obs)
        self.assertEqual(len(obs["filings"]), 2)
        d = udelta.plan(self.tables, obs,
                        uapply.load_manifest(self.ds)
                        ["corpus_logical_sha256"])
        self.assertTrue(all(t["transition"] == "NO_CHANGE"
                            for t in d["transitions"]))
        self.assertFalse(any(d["rows_added"].values()))
        self.assertFalse(any(d["rows_updated"].values()))
        self.assertFalse(any(d["rows_removed"].values()))

    def test_changed_package_needs_taxonomy(self):
        m = json.loads(json.dumps(self.manifest))
        m["esef_views"][0]["package"]["sha256"] = "dd" * 32
        m["esef_views"][0]["variant_artifact_set_id"] = artifact_set_id(
            [{"role": "ESEF_PACKAGE_ZIP_XBRL", "sha256": "dd" * 32}])
        with self.assertRaises(C.CaptureError):
            casm.assemble_observation(
                m, tables=self.tables,
                evidence_root=Path(self._tmp.name))

    def test_missing_view_is_capture_error(self):
        m = json.loads(json.dumps(self.manifest))
        m["esef_views"] = [v for v in m["esef_views"]
                           if v["requested_ui_language"] != "es"]
        with self.assertRaises(C.CaptureError):
            casm.assemble_observation(
                m, tables=self.tables,
                evidence_root=Path(self._tmp.name))

    def test_unlisted_ipp_skipped_not_removed(self):
        m = json.loads(json.dumps(self.manifest))
        m["ipp_filings"] = []
        obs = casm.assemble_observation(
            m, tables=self.tables,
            evidence_root=Path(self._tmp.name))
        self.assertEqual(len(obs["filings"]), 1)
        d = udelta.plan(self.tables, obs,
                        uapply.load_manifest(self.ds)
                        ["corpus_logical_sha256"])
        # the IPP filing is absent from the observation: untouched,
        # no removal claim
        self.assertFalse(any(d["rows_removed"].values()))

    def test_bootstrap_assembly_without_base(self):
        # no tables -> everything is a fresh filing; parse is required
        # for states, so no taxonomy dir -> fail closed
        with self.assertRaises(C.CaptureError):
            casm.assemble_observation(
                self.manifest, tables=None,
                evidence_root=Path(self._tmp.name))


# ---------------------------------------------------------------- CLI

class TestCliUpdate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ds = build_ds(Path(self._tmp.name) / "ds")
        self.tables = uapply.load_tables(self.ds)
        obs = casm.assemble_observation(
            synthetic_manifest(), tables=self.tables,
            evidence_root=Path(self._tmp.name))
        self.obs_path = Path(self._tmp.name) / "obs.json"
        self.obs_path.write_text(
            json.dumps(obs, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _snap(self):
        return {p.name: sha256_bytes(p.read_bytes())
                for p in sorted(self.ds.rglob("*")) if p.is_file()}

    def test_observation_offline_dry_run(self):
        before = self._snap()
        with deny_network():
            code, out, err = run_cli([
                "update", "--dataset", str(self.ds),
                "--observation", str(self.obs_path), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("NO_CHANGE", out)
        self.assertIn("dry-run", out)
        self.assertEqual(before, self._snap())

    def test_observation_apply_no_change(self):
        before = self._snap()
        with deny_network():
            code, out, err = run_cli([
                "update", "--dataset", str(self.ds),
                "--observation", str(self.obs_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("NO_CHANGE", out)
        self.assertEqual(before, self._snap())

    def test_evidence_dir_offline(self):
        ev = Path(self._tmp.name) / "ev"
        store = cfetch.EvidenceStore(ev)
        m = dict(synthetic_manifest())
        store.finish_run(m)
        with deny_network():
            code, out, err = run_cli([
                "update", "--dataset", str(self.ds),
                "--evidence-dir", str(ev), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("NO_CHANGE", out)

    def test_tampered_observation_refused(self):
        obs = json.loads(self.obs_path.read_text(encoding="utf-8"))
        obs["observation_sha256"] = "0" * 64
        self.obs_path.write_text(json.dumps(obs), encoding="utf-8")
        code, out, err = run_cli([
            "update", "--dataset", str(self.ds),
            "--observation", str(self.obs_path)])
        self.assertEqual(code, 5)
        self.assertIn("mismatch", err)

    def test_missing_dataset(self):
        code, _, _ = run_cli([
            "update", "--dataset", str(Path(self._tmp.name) / "nope"),
            "--observation", str(self.obs_path)])
        self.assertEqual(code, 3)

    def test_observe_bad_issuer_exits_7(self):
        with tempfile.TemporaryDirectory() as td:
            code, _, err = run_cli([
                "observe", "--evidence-dir", td,
                "--issuer", "X99999999"])
        self.assertEqual(code, 7)
        self.assertIn("frozen corpus", err)

    def test_observe_network_failure_exits_7(self):
        import requests
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(
                    requests.Session, "get",
                    side_effect=requests.ConnectionError("down")):
                code, _, err = run_cli([
                    "observe", "--evidence-dir", td,
                    "--issuer", "A-48010615", "--family", "ipp",
                    "--min-delay", "0"])
        self.assertEqual(code, 7)


def bootstrap_obs() -> dict:
    """CANONICAL_OBSERVATION_V1 for an empty base, built from the
    fixture filings (states empty — parse coverage lives in the gate
    legs over preserved evidence)."""
    obs = {
        "observation_format": "CANONICAL_OBSERVATION_V1",
        "observation_id": "obs-test-bootstrap",
        "captured_at": "2026-09-17T00:00:00Z",
        "filings": [
            {"filing": _filing_ibe(), "states": [],
             "extension_mapping_files": [], "extra_artifacts": [],
             "extras": None},
            {"filing": _filing_ipp(), "states": [],
             "extension_mapping_files": [], "extra_artifacts": [],
             "extras": None}]}
    obs["observation_sha256"] = uobs.observation_sha256(obs)
    return obs


class TestCliInit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ds = self.root / "ds"
        self.obs_path = self.root / "obs.json"
        self.obs_path.write_text(
            json.dumps(bootstrap_obs(), ensure_ascii=False,
                       sort_keys=True), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _init(self):
        return run_cli([
            "init", "--dataset", str(self.ds),
            "--observation", str(self.obs_path)])

    def test_init_observation_bootstraps_valid_dataset(self):
        with deny_network():
            code, out, err = self._init()
        self.assertEqual(code, 0, err)
        self.assertIn("INITIALIZED", out)
        # the staged result is a complete, verifiable dataset — and it
        # carries exactly the rows a hand-built dataset over the same
        # filings would (no fabricated overlays)
        from opencnmv.dataset import manifest as dmanifest
        man = uapply.load_manifest(self.ds)
        self.assertEqual(dmanifest.verify_manifest(self.ds, man), [])
        ref = build_ds(self.root / "ref")
        got = uapply.load_tables(self.ds)
        exp = uapply.load_tables(ref)
        self.assertEqual(got, exp)
        filing_rows = {r["filing_id"]: r for r in got["filing"]}
        self.assertTrue(all(r["extras_json"] is None
                            for r in filing_rows.values()))
        # bootstrap is the update fixpoint: same observation -> NO_CHANGE
        with deny_network():
            code, out, err = run_cli([
                "update", "--dataset", str(self.ds),
                "--observation", str(self.obs_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("NO_CHANGE", out)

    def test_init_is_byte_deterministic(self):
        ds2 = self.root / "ds2"
        with deny_network():
            code1, _, err1 = self._init()
            code2, _, err2 = run_cli([
                "init", "--dataset", str(ds2),
                "--observation", str(self.obs_path)])
        self.assertEqual((code1, code2), (0, 0), err1 + err2)

        def h(d):
            return {p.name: sha256_bytes(p.read_bytes())
                    for p in sorted(d.rglob("*")) if p.is_file()}
        self.assertEqual(h(self.ds), h(ds2))

    def test_init_requires_explicit_dataset(self):
        code, _, err = run_cli([
            "init", "--observation", str(self.obs_path)])
        self.assertEqual(code, 2)
        self.assertIn("--dataset", err)

    def test_init_refuses_nonempty_destination(self):
        with deny_network():
            code, _, err = self._init()
        self.assertEqual(code, 0, err)
        code, _, err = self._init()
        self.assertEqual(code, 2)
        self.assertIn("not empty", err)
        self.assertIn("no overwrite", err)

    def test_init_source_combination_errors(self):
        for extra in (["--live"], ["--evidence-dir", str(self.root)],
                      ["--taxonomy-dir", str(self.root)],
                      ["--run", "cap-x"], ["--issuer", "A-48010615"]):
            code, _, err = run_cli([
                "init", "--dataset", str(self.root / "x"),
                "--observation", str(self.obs_path), *extra])
            self.assertEqual(code, 2, f"{extra}: {err}")
        # --evidence-dir / --live require --taxonomy-dir
        code, _, err = run_cli([
            "init", "--dataset", str(self.root / "x"),
            "--evidence-dir", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("--taxonomy-dir", err)
        code, _, err = run_cli([
            "init", "--dataset", str(self.root / "x"),
            "--live", "--evidence-dir", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("--taxonomy-dir", err)
        # --live requires --evidence-dir
        code, _, err = run_cli([
            "init", "--dataset", str(self.root / "x"), "--live"])
        self.assertEqual(code, 2)
        # capture-only flags need --live
        code, _, err = run_cli([
            "init", "--dataset", str(self.root / "x"),
            "--evidence-dir", str(self.root),
            "--taxonomy-dir", str(self.root),
            "--issuer", "A-48010615"])
        self.assertEqual(code, 2)
        self.assertIn("--live", err)

    def test_init_failure_leaves_no_dataset(self):
        from opencnmv.update import bootstrap as uboot
        obs = bootstrap_obs()
        with self.assertRaises(RuntimeError):
            uboot.init_dataset(self.ds, obs,
                               fail_hook="during_table:filing")
        self.assertFalse((self.ds / "dataset_manifest.json").exists())
        self.assertFalse(list(self.root.glob("*.staging-*")))
        # a later good init still works (staging is not authoritative)
        res = uboot.init_dataset(self.ds, obs)
        self.assertEqual(res["status"], "INITIALIZED")
