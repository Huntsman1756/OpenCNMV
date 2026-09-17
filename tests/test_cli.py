"""Tests for opencnmv.query + opencnmv.cli over a tiny inline
COLUMNAR_DATASET_V1 fixture — no gate code, no network, no frozen
evidence. The fixture exercises every public semantic class: dual
variants, fallback view resolution, scoped/unobservable events, PROVEN
and non-PROVEN mappings, typed dims, compound units, fact multiplicity,
and the divergent-payload case.
"""
from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from opencnmv.cli.main import entry
from opencnmv.dataset import manifest as dmanifest
from opencnmv.dataset import parquetio, schema as dschema, tables
from opencnmv.provenance.hashes import sha256_bytes
from opencnmv.query import compare as qcompare
from opencnmv.query import dataset as qds
from opencnmv.query.errors import (DatasetIntegrityError,
                                   DatasetNotFoundError)

NS = "http://xbrl.ifrs.org/taxonomy#ifrs-full"
EXT_ES = "http://issuer.example/es#"
EXT_EN = "http://issuer.example/en#"
MON = "http://www.xbrl.org/2003/instance#monetaryItemType"
TXT = "http://www.xbrl.org/2003/instance#textBlockItemType"
EUR = "http://www.xbrl.org/2003/iso4217#EUR"
SHARES = "http://www.xbrl.org/2003/instance#shares"
DIM = "http://cnmv.example/dim#"


def _rec(concept, value, *, state_lang="es", ctype=MON, numeric=True,
         dims=None, unit=EUR, decimals="0", period=("2024-01-01",
                                                  "2024-12-31")):
    v = value if isinstance(value, str) else json.dumps(value)
    return {
        "concept": concept,
        "value_sha256": sha256_bytes(v.encode()), "value_len": len(v),
        "value_preview": v, "xValue_sha256": sha256_bytes(v.encode()),
        "xValue_len": len(v), "xValue_preview": v, "isNil": False,
        "decimals": decimals, "contextID": "c", "unitID": "u",
        "lang": state_lang, "concept_type": ctype,
        "is_numeric": numeric, "value_full": v, "xValue_full": v,
        "ns_kind": ("issuer_extension" if concept.startswith(
            (EXT_ES, EXT_EN)) else "taxonomy"),
        "entity_scheme": "http://s", "entity": "E",
        "period_start": period[0], "period_end": period[1],
        "dimensions": dims or {}, "unit": unit, "_profile": "esef"}


def _filing_a() -> dict:
    """Dual-variant filing: #es + #en, one of every compare class."""
    return {
        "filing_id": "cnmv:ifa:7",
        "issuer": {"denomination": "DUAL, S.A.", "nif": "A7",
                   "lei": "LEI7"},
        "registro_oficial": "7", "family": "ESEF_IFA",
        "period_end": "2024-12-31",
        "filing_versions": [{
            "filing_version_id": "cnmv:ifa:7#nreg:7",
            "source_nreg": "7", "filed_at": "2025-03-01",
            "submission_kind": "ORIGINAL_SUBMISSION"}],
        "submission_variants": [
            {"variant_id": "cnmv:ifa:7#es", "filing_id": "cnmv:ifa:7",
             "submission_language": "es",
             "variant_versions": [{
                 "variant_version_id": "cnmv:ifa:7#es#v1",
                 "variant_id": "cnmv:ifa:7#es", "observed": True,
                 "artifact_set_id": "set-es",
                 "artifacts": [{
                     "artifact_id": "sha256:" + "a1" * 32,
                     "role": "REPORT", "sha256": "a1" * 32, "bytes": 10,
                     "media_type": "application/xml",
                     "package_lang_tag": "es"}],
                 "created_by_event_id": None,
                 "supersedes_variant_version_id": None}]},
            {"variant_id": "cnmv:ifa:7#en", "filing_id": "cnmv:ifa:7",
             "submission_language": "en",
             "variant_versions": [{
                 "variant_version_id": "cnmv:ifa:7#en#v1",
                 "variant_id": "cnmv:ifa:7#en", "observed": True,
                 "artifact_set_id": "set-en",
                 "artifacts": [{
                     "artifact_id": "sha256:" + "a2" * 32,
                     "role": "REPORT", "sha256": "a2" * 32, "bytes": 10,
                     "media_type": "application/xml",
                     "package_lang_tag": "en"}],
                 "created_by_event_id": None,
                 "supersedes_variant_version_id": None}]}],
        "view_resolutions": [
            {"requested_ui_language": "es",
             "resolved_variant_id": "cnmv:ifa:7#es",
             "resolution_mode": "SUBMITTED_VARIANT"},
            {"requested_ui_language": "en",
             "resolved_variant_id": "cnmv:ifa:7#en",
             "resolution_mode": "SUBMITTED_VARIANT"}],
        "version_events": [],
        "extension_mappings": []}


def _filing_b() -> dict:
    """Single-variant filing with EN fallback + unobservable-scope event
    + a scoped replacement creating a second #es version."""
    return {
        "filing_id": "cnmv:ifa:8",
        "issuer": {"denomination": "SOLO, S.A.", "nif": "A8"},
        "registro_oficial": "8", "family": "IPP",
        "period_end": "30/06/2025",
        "filing_versions": [{
            "filing_version_id": "cnmv:ifa:8#nreg:8",
            "source_nreg": "8", "filed_at": "2025-07-01",
            "submission_kind": "ORIGINAL_SUBMISSION"}],
        "submission_variants": [
            {"variant_id": "cnmv:ifa:8#es", "filing_id": "cnmv:ifa:8",
             "submission_language": "es",
             "variant_versions": [
                 {"variant_version_id": "cnmv:ifa:8#es#v1",
                  "variant_id": "cnmv:ifa:8#es", "observed": True,
                  "artifact_set_id": "set-b1",
                  "artifacts": [{
                      "artifact_id": "sha256:" + "b1" * 32,
                      "role": "REPORT", "sha256": "b1" * 32, "bytes": 5,
                      "media_type": "application/xml",
                      "package_lang_tag": "es"}],
                  "created_by_event_id": None,
                  "supersedes_variant_version_id": None},
                 {"variant_version_id": "cnmv:ifa:8#es#v2",
                  "variant_id": "cnmv:ifa:8#es", "observed": True,
                  "artifact_set_id": "set-b2",
                  "artifacts": [{
                      "artifact_id": "sha256:" + "b2" * 32,
                      "role": "REPORT", "sha256": "b2" * 32, "bytes": 5,
                      "media_type": "application/xml",
                      "package_lang_tag": "es"}],
                  "created_by_event_id": "cnmv:ifa:8#evt:2025-09-01",
                  "supersedes_variant_version_id": "cnmv:ifa:8#es#v1"}]}],
        "view_resolutions": [
            {"requested_ui_language": "es",
             "resolved_variant_id": "cnmv:ifa:8#es",
             "resolution_mode": "SUBMITTED_VARIANT"},
            {"requested_ui_language": "en",
             "resolved_variant_id": "cnmv:ifa:8#es",
             "resolution_mode": "FALLBACK_TO_ES"}],
        "version_events": [
            {"event_id": "cnmv:ifa:8#evt:2025-08-15",
             "event_date": "2025-08-15", "event_type": "SUBSTITUTION",
             "source_label": "generic substitution notice",
             "source_nreg": None, "evidence_artifact_id": None,
             "scope_status": "VARIANT_SCOPE_NOT_OBSERVABLE",
             "affects": [{
                 "variant_id": None,
                 "affected_component_scope": "NOT_IDENTIFIED",
                 "component_description": "scope not derivable",
                 "before_variant_version_id": None,
                 "after_variant_version_id": None,
                 "scope_basis": None}]},
            {"event_id": "cnmv:ifa:8#evt:2025-09-01",
             "event_date": "2025-09-01", "event_type": "SUBSTITUTION",
             "source_label": "es replacement", "source_nreg": "9",
             "evidence_artifact_id": None,
             "scope_status": "ES_ONLY_REPLACED",
             "affects": [{
                 "variant_id": "cnmv:ifa:8#es",
                 "affected_component_scope": "SOURCE_DESCRIBED",
                 "component_description": "es package",
                 "before_variant_version_id": "cnmv:ifa:8#es#v1",
                 "after_variant_version_id": "cnmv:ifa:8#es#v2",
                 "scope_basis": None}]}],
        "extension_mappings": []}


def _facts() -> tuple[list[dict], list[dict]]:
    """(facts_rows, fact_dimension_rows) for both filings."""
    es, en = "cnmv:ifa:7#es#v1", "cnmv:ifa:7#en#v1"
    b1, b2 = "cnmv:ifa:8#es#v1", "cnmv:ifa:8#es#v2"
    specs = [
        # (rec, vvid, state, seq, fact_id)
        (_rec(f"{NS}#C0", "100"), es, "A-es", 0, "fact:e00"),
        (_rec(f"{NS}#C1", "98000000", decimals="-6"), es, "A-es", 1,
         "fact:e01"),
        (_rec(f"{NS}#C2", "0.9", decimals="1"), es, "A-es", 2,
         "fact:e02"),
        (_rec(f"{NS}#T1", "informe", ctype=TXT, numeric=False,
              unit=None, decimals=None), es, "A-es", 3, "fact:e03"),
        (_rec(f"{NS}#ONLYES", "1"), es, "A-es", 4, "fact:e04"),
        (_rec(f"{EXT_ES}Capex", "5"), es, "A-es", 5, "fact:e05"),
        (_rec(f"{EXT_ES}Solo", "7"), es, "A-es", 6, "fact:e06"),
        (_rec(f"{EXT_ES}Amb", "9"), es, "A-es", 7, "fact:e07"),
        (_rec(f"{NS}#Dup", "42"), es, "A-es", 8, "fact:e08"),
        (_rec(f"{NS}#Dup", "42"), es, "A-es", 9, "fact:e08#1"),
        (_rec(f"{NS}#Typed", "1",
              dims={f"{DIM}AxisT": "T:2024"}), es, "A-es", 10,
         "fact:e10"),
        (_rec(f"{NS}#PerShare", "3", unit=f"{EUR}/{SHARES}"),
         es, "A-es", 11, "fact:e11"),
        (_rec(f"{NS}#C0", "100", state_lang="en"), en, "A-en", 0,
         "fact:n00"),
        (_rec(f"{NS}#C1", "-98000000", decimals="-6", state_lang="en"),
         en, "A-en", 1, "fact:n01"),
        (_rec(f"{NS}#C2", "0.900", decimals="2", state_lang="en"),
         en, "A-en", 2, "fact:n02"),
        (_rec(f"{NS}#T1", "report", ctype=TXT, numeric=False, unit=None,
              decimals=None, state_lang="en"), en, "A-en", 3,
         "fact:n03"),
        (_rec(f"{EXT_EN}CapitalExpenditure", "5", state_lang="en"),
         en, "A-en", 4, "fact:n05"),
        (_rec(f"{EXT_EN}AmbTwin", "9", state_lang="en"), en, "A-en", 5,
         "fact:n07"),
        (_rec(f"{NS}#Dup", "42", state_lang="en"), en, "A-en", 6,
         "fact:n08"),
        (_rec(f"{NS}#Dup", "42", state_lang="en"), en, "A-en", 7,
         "fact:n08#1"),
        (_rec(f"{NS}#Typed", "1", state_lang="en",
              dims={f"{DIM}AxisT": "T:2024"}), en, "A-en", 8,
         "fact:n10"),
        (_rec(f"{NS}#PerShare", "3", state_lang="en",
              unit=f"{EUR}/{SHARES}"), en, "A-en", 9, "fact:n11"),
        # filing B: H2-style pair — same concept+period_end, distinct
        # context dims must stay separate; second copy lives on v2
        (_rec(f"{NS}#H2", "1", state_lang="es",
              dims={f"{DIM}Periodo": "E:MiembroActual"}), b1,
         "B-2025", 0, "fact:b01"),
        (_rec(f"{NS}#H2", "2", state_lang="es",
              dims={f"{DIM}Periodo": "E:MiembroAnterior"}), b2,
         "B-2025b", 0, "fact:b02"),
    ]
    frows, drows = [], []
    for rec, vvid, state, seq, fid in specs:
        r, d = tables.fact_rows(rec, vvid, state, seq, fid)
        frows.append(r)
        drows.extend(d)
    return frows, drows


def _provenance() -> list[dict]:
    rows = []
    for state, fid, vvid, art in (
            ("A-es", "cnmv:ifa:7", "cnmv:ifa:7#es#v1", "a1" * 32),
            ("A-en", "cnmv:ifa:7", "cnmv:ifa:7#en#v1", "a2" * 32),
            ("B-2025", "cnmv:ifa:8", "cnmv:ifa:8#es#v1", "b1" * 32),
            ("B-2025b", "cnmv:ifa:8", "cnmv:ifa:8#es#v2", "b2" * 32)):
        rows.append({
            "state_id": state, "filing_id": fid,
            "variant_version_id": vvid, "artifact_id": f"sha256:{art}",
            "role": "REPORT", "sha256": art, "byte_size": 10,
            "media_type": "application/xml",
            "source_url": "https://cnmv.example/doc", "resolved_url": None,
            "retrieved_at": "2025-01-01T00:00:00Z", "http_status": 200,
            "evidence_path": "evidence/pkg.zip", "arelle_version": "t",
            "lexical_shim": False})
    return rows


def build_minids(dest: Path) -> Path:
    """Materialize the inline fixture as a valid COLUMNAR_DATASET_V1."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    rows_a = tables.filing_rows(_filing_a())
    rows_b = tables.filing_rows(_filing_b())
    tbl: dict[str, list[dict]] = {
        t: rows_a.get(t, []) + rows_b.get(t, [])
        for t in dschema.TABLE_ORDER}
    tbl["extension_mapping"] = tables.mapping_rows(
        "cnmv:ifa:7", "es", "en", [
            {"source_qname": f"{EXT_ES}Capex",
             "target_qname": f"{EXT_EN}CapitalExpenditure",
             "pair_id": "pair:capex", "mapping_type": "CONCEPT",
             "verdict": "PROVEN_EQUIVALENT", "evidence": ["x"]},
            {"source_qname": f"{EXT_ES}Amb",
             "target_qname": f"{EXT_EN}AmbTwin",
             "pair_id": "pair:amb", "mapping_type": "CONCEPT",
             "verdict": "AMBIGUOUS", "evidence": []},
            {"source_qname": f"{EXT_ES}Solo",
             "target_qname": None, "pair_id": None,
             "mapping_type": None, "verdict": "UNMATCHED",
             "evidence": []}],
        "map.json")
    tbl["facts"], tbl["fact_dimension"] = _facts()
    tbl["provenance"] = _provenance()
    meta = {}
    for t in dschema.TABLE_ORDER:
        ordered = sorted(tbl[t], key=parquetio.ROW_ORDER[t])
        meta[t] = parquetio.write_table(t, ordered, dest / f"{t}.parquet")
    man = dmanifest.build_manifest(
        inputs={"fixture": {"path": "tests/test_cli.py",
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


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """In-process CLI invocation -> (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = entry(argv)
    return code, out.getvalue(), err.getvalue()


class deny_network:
    """Fail any socket use. The CLI must be pure local computation."""

    def __enter__(self):
        def blocked(*a, **k):
            raise AssertionError("network access attempt")

        self._patchers = [mock.patch.object(socket, n, blocked)
                          for n in ("socket", "create_connection",
                                    "getaddrinfo", "gethostbyname")]
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()


class CliFixture(unittest.TestCase):
    ds_path: Path
    _tmp: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ds_path = build_minids(Path(cls._tmp.name) / "ds")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def cli(self, *argv):
        return run_cli(["--dataset", str(self.ds_path), *argv])


class TestOpenAndValidate(CliFixture):
    def test_open_ok(self):
        with qds.open_dataset(self.ds_path) as ds:
            info = qds.dataset_info(ds)
        self.assertEqual(info["dataset_version"], "COLUMNAR_DATASET_V1")
        self.assertEqual(info["counts"]["filings"], 2)

    def test_validate_pass(self):
        with qds.open_dataset(self.ds_path) as ds:
            rep = qds.validate_dataset(ds)
        self.assertEqual(rep["status"], "PASS",
                         [c for c in rep["checks"]
                          if c["status"] != "PASS"])

    def test_missing_dir(self):
        with self.assertRaises(DatasetNotFoundError):
            qds.open_dataset(Path(self._tmp.name) / "nope")

    def test_corrupt_byte_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            import shutil
            dst = Path(td) / "ds"
            shutil.copytree(self.ds_path, dst)
            p = dst / "facts.parquet"
            b = bytearray(p.read_bytes())
            b[20] ^= 0xFF
            p.write_bytes(bytes(b))
            with self.assertRaises(DatasetIntegrityError):
                qds.open_dataset(dst)

    def test_deleted_table_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            import shutil
            dst = Path(td) / "ds"
            shutil.copytree(self.ds_path, dst)
            (dst / "facts.parquet").unlink()
            with self.assertRaises(DatasetIntegrityError):
                qds.open_dataset(dst)


class TestQuerySemantics(CliFixture):
    def test_filings_filters(self):
        code, out, _ = self.cli("filings", "--json")
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual([r["filing_id"] for r in rows],
                         ["cnmv:ifa:7", "cnmv:ifa:8"])
        code, out, _ = self.cli("filings", "--family", "IPP", "--json")
        self.assertEqual(json.loads(out)[0]["family"], "IPP")
        code, out, _ = self.cli("filings", "--issuer", "dual", "--json")
        self.assertEqual(len(json.loads(out)), 1)

    def test_filing_detail_graph(self):
        code, out, _ = self.cli("filing", "8", "--json")
        self.assertEqual(code, 0)
        f = json.loads(out)["filing"]
        self.assertEqual(len(f["submission_variants"]), 1)
        self.assertEqual(len(f["submission_variants"][0]
                             ["variant_versions"]), 2)
        self.assertEqual(f["version_events"][1]["affects"][0]
                         ["after_variant_version_id"], "cnmv:ifa:8#es#v2")
        # fallback resolution present, no phantom #en
        modes = {v["resolution_mode"] for v in f["view_resolutions"]}
        self.assertEqual(modes, {"SUBMITTED_VARIANT", "FALLBACK_TO_ES"})
        self.assertEqual(len(f["submission_variants"]), 1)

    def test_history_scoped_events(self):
        code, out, _ = self.cli("history", "cnmv:ifa:8", "--json")
        self.assertEqual(code, 0)
        h = json.loads(out)
        ev = {e["event_id"]: e for e in h["version_events"]}
        unobs = ev["cnmv:ifa:8#evt:2025-08-15"]
        self.assertEqual(unobs["scope_status"],
                         "VARIANT_SCOPE_NOT_OBSERVABLE")
        self.assertIsNone(unobs["affects"][0]["variant_id"])
        repl = ev["cnmv:ifa:8#evt:2025-09-01"]
        self.assertEqual(repl["affects"][0]["variant_id"],
                         "cnmv:ifa:8#es")

    def test_compare_all_classes(self):
        code, out, _ = self.cli("compare", "cnmv:ifa:7", "--json")
        self.assertEqual(code, 0)
        rep = json.loads(out)
        self.assertEqual(rep["status"], "COMPARED")
        c = rep["counts"]
        self.assertEqual(c["DIVERGENT_SUBMISSION_FACT"], 1)
        self.assertEqual(c["MATCH_NUMERIC_EQUIVALENT"], 1)
        self.assertEqual(c["LANGUAGE_SENSITIVE_NOT_COMPARED"], 1)
        self.assertEqual(c["VARIANT_ONLY_FACT"], 1)
        # unmapped ext facts: es Solo + es/en ambiguous pair never merge
        self.assertEqual(c["UNMAPPED_VARIANT_FACT"], 3)
        div = [r for r in rep["records"]
               if r["class"] == "DIVERGENT_SUBMISSION_FACT"][0]
        self.assertEqual(div["es"]["value"], "98000000")
        self.assertEqual(div["en"]["value"], "-98000000")
        # the AMBIGUOUS pair (identical payload) must NOT merge
        unmapped = {r["payload"]["fact_id"] for r in rep["records"]
                    if r["class"] == "UNMAPPED_VARIANT_FACT"}
        self.assertEqual(unmapped, {"fact:e06", "fact:e07", "fact:n07"})

    def test_compare_single_variant(self):
        code, out, _ = self.cli("compare", "cnmv:ifa:8", "--json")
        rep = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(rep["status"], "SKIPPED_SINGLE_VARIANT")

    def test_facts_multiplicity_and_dims(self):
        code, out, _ = self.cli("facts", "--state", "A-es",
                                "--concept", "#Dup", "--json")
        res = json.loads(out)
        self.assertEqual(res["total"], 2)
        self.assertEqual({f["fact_id"] for f in res["facts"]},
                         {"fact:e08", "fact:e08#1"})
        code, out, _ = self.cli("fact", "fact:e10", "--json")
        f = json.loads(out)
        self.assertEqual(f["dimensions"][0]["dim_kind"], "T")
        self.assertEqual(f["dimensions"][0]["typed_value"], "2024")
        self.assertEqual(
            list(f["canonical_record"]["dimensions"].values()),
            ["T:2024"])
        code, out, _ = self.cli("fact", "fact:e11", "--json")
        f = json.loads(out)
        self.assertEqual(f["unit_denominator"], [SHARES])
        self.assertEqual(f["unit_numerator"], [EUR])

    def test_facts_bounded(self):
        code, out, _ = self.cli("facts", "--state", "A-es",
                                "--limit", "3", "--json")
        res = json.loads(out)
        self.assertTrue(res["truncated"])
        self.assertEqual(len(res["facts"]), 3)
        code, out, _ = self.cli("facts", "--state", "A-es", "--count")
        self.assertEqual(out.strip(), "12")

    def test_mappings_verdicts(self):
        code, out, _ = self.cli("mappings", "cnmv:ifa:7", "--json")
        rep = json.loads(out)
        self.assertEqual(rep["counts_by_verdict"],
                         {"PROVEN_EQUIVALENT": 1, "AMBIGUOUS": 1,
                          "UNMATCHED": 1})
        rw = {m["verdict"]: m["rewrites_identity"]
              for m in rep["mappings"]}
        self.assertEqual(rw, {"PROVEN_EQUIVALENT": True,
                              "AMBIGUOUS": False, "UNMATCHED": False})

    def test_provenance_chain(self):
        code, out, _ = self.cli("provenance", "--fact", "fact:e01",
                                "--json")
        rep = json.loads(out)
        self.assertEqual(code, 0)
        p = rep["provenance"][0]
        self.assertEqual(p["source_artifact"]["sha256"], "a1" * 32)
        self.assertEqual(p["source_artifact"]["evidence_path"],
                         "evidence/pkg.zip")
        self.assertEqual(p["context"]["variant_version_id"],
                         "cnmv:ifa:7#es#v1")

    def test_events(self):
        code, out, _ = self.cli("events", "cnmv:ifa:8", "--jsonl")
        self.assertEqual(code, 0)
        rows = [json.loads(x) for x in out.splitlines()]
        self.assertEqual(len(rows), 2)


class TestExitCodes(CliFixture):
    def test_not_found(self):
        code, _, err = self.cli("filing", "cnmv:ifa:999")
        self.assertEqual(code, 4)
        self.assertIn("no filing", err)

    def test_missing_dataset(self):
        code, _, _ = run_cli(
            ["--dataset", str(self.ds_path) + "nope", "dataset", "info"])
        self.assertEqual(code, 3)

    def test_usage_error(self):
        with self.assertRaises(SystemExit) as cm:
            run_cli(["--dataset", str(self.ds_path), "filings",
                     "--bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_integrity_exit5(self):
        with tempfile.TemporaryDirectory() as td:
            import shutil
            dst = Path(td) / "ds"
            shutil.copytree(self.ds_path, dst)
            (dst / "filing.parquet").unlink()
            code, _, err = run_cli(
                ["--dataset", str(dst), "dataset", "info"])
            self.assertEqual(code, 5)
            self.assertIn("manifest verification", err)


class TestDeterminismAndSafety(CliFixture):
    CORPUS = [
        ["dataset", "info"], ["dataset", "validate"],
        ["filings"], ["filings", "--jsonl"], ["filings", "--json"],
        ["filing", "cnmv:ifa:7"], ["filing", "cnmv:ifa:8", "--json"],
        ["history", "cnmv:ifa:8"], ["history", "cnmv:ifa:7", "--json"],
        ["facts", "--state", "A-es"], ["facts", "--jsonl"],
        ["facts", "--state", "A-es", "--count"],
        ["fact", "fact:e01"], ["fact", "fact:e10", "--json"],
        ["compare", "cnmv:ifa:7"], ["compare", "cnmv:ifa:7", "--json"],
        ["compare", "cnmv:ifa:8"],
        ["events"], ["events", "cnmv:ifa:8", "--jsonl"],
        ["mappings", "cnmv:ifa:7"], ["mappings", "cnmv:ifa:7", "--json"],
        ["provenance", "--fact", "fact:e01"],
        ["provenance", "--artifact", "sha256:" + "b1" * 32],
        ["provenance", "--state", "A-es"],
    ]

    def _hash_dataset(self) -> dict[str, str]:
        return {str(p.relative_to(self.ds_path)): sha256_bytes(
            p.read_bytes())
            for p in sorted(self.ds_path.rglob("*")) if p.is_file()}

    def test_read_only_and_deterministic(self):
        before = self._hash_dataset()
        outs = {}
        with deny_network():
            for argv in self.CORPUS:
                code, out, err = self.cli(*argv)
                self.assertEqual(code, 0, f"{argv}: {err}")
                outs[json.dumps(argv)] = out
        self.assertEqual(before, self._hash_dataset())
        with deny_network():
            for argv in self.CORPUS:
                code, out, _ = self.cli(*argv)
                self.assertEqual(code, 0)
                self.assertEqual(out, outs[json.dumps(argv)],
                                 f"nondeterministic output: {argv}")

    def test_jsonl_is_data_only(self):
        code, out, err = self.cli("filings", "--jsonl")
        rows = [json.loads(x) for x in out.splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(err, "")

    def test_no_ansi_no_absolute_paths(self):
        code, out, _ = self.cli("provenance", "--fact", "fact:e01",
                                "--json")
        self.assertNotIn("\x1b[", out)
        self.assertNotIn(str(self.ds_path), out)


class TestComparePure(unittest.TestCase):
    def test_pairing_is_multiset_not_cross_product(self):
        """Two identical facts on one side vs one on the other: one pair
        + one VARIANT_ONLY, never two matches."""
        es = [{"concept": "ns#C", "entity_scheme": "s", "entity": "E",
               "period": "2024", "unit": "u", "dims": {}, "lang": "es",
               "value_sha256": "x", "decimals": "0", "isNil": False,
               "is_numeric": True, "concept_type": "m",
               "value": "1", "xValue": "1", "fact_id": "f1", "seq": 0,
               "ns_kind": "taxonomy"},
              {"concept": "ns#C", "entity_scheme": "s", "entity": "E",
               "period": "2024", "unit": "u", "dims": {}, "lang": "es",
               "value_sha256": "x", "decimals": "0", "isNil": False,
               "is_numeric": True, "concept_type": "m",
               "value": "1", "xValue": "1", "fact_id": "f2", "seq": 1,
               "ns_kind": "taxonomy"}]
        en = [dict(es[0], fact_id="g1", lang="en")]
        rep = qcompare.compare_variants(es, en, set(), set(), {})
        self.assertEqual(rep["counts"]["MATCH_EXACT"], 1)
        self.assertEqual(rep["counts"]["VARIANT_ONLY_FACT"], 1)


if __name__ == "__main__":
    unittest.main()
