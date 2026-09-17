"""Unit tests for opencnmv.dataset (COLUMNAR_DATASET_V1).

These test the production decomposition/reconstruction, deterministic
Parquet I/O, manifest verification and logical integrity in isolation —
no gate code, no frozen evidence beyond tiny inline fixtures.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opencnmv.dataset import integrity, manifest, parquetio, schema, tables
from opencnmv.serialize import canonical_bytes


def mini_filing() -> dict:
    """Smallest schema-conformant canonical filing with one of each
    relational feature (dual variant, supersession, scoped event)."""
    return {
        "filing_id": "cnmv:ifa:1",
        "issuer": {"denomination": "X, S.A.", "lei": "L"},
        "registro_oficial": "1",
        "family": "ESEF_IFA",
        "period_end": "31/12/2024",
        "filing_versions": [{
            "filing_version_id": "cnmv:ifa:1#nreg:9",
            "source_nreg": "9", "filed_at": "2025-02-01",
            "submission_kind": "ORIGINAL_SUBMISSION"}],
        "submission_variants": [
            {"variant_id": "cnmv:ifa:1#es", "filing_id": "cnmv:ifa:1",
             "submission_language": "es",
             "variant_versions": [{
                 "variant_version_id": "cnmv:ifa:1#es#v1",
                 "variant_id": "cnmv:ifa:1#es", "observed": True,
                 "artifact_set_id": "aa",
                 "artifacts": [{
                     "artifact_id": "sha256:a1", "role": "ESEF_PACKAGE_ZIP_XBRL",
                     "sha256": "a1", "bytes": 1, "media_type": "application/zip",
                     "package_lang_tag": "es"}],
                 "created_by_event_id": "cnmv:ifa:1#evt:e",
                 "supersedes_variant_version_id": None}]}],
        "view_resolutions": [
            {"requested_ui_language": "es",
             "resolved_variant_id": "cnmv:ifa:1#es",
             "resolution_mode": "SUBMITTED_VARIANT"},
            {"requested_ui_language": "en",
             "resolved_variant_id": "cnmv:ifa:1#es",
             "resolution_mode": "FALLBACK_TO_ES"}],
        "version_events": [{
            "event_id": "cnmv:ifa:1#evt:e", "event_date": "2025-02-01",
            "event_type": "SUBSTITUTION", "source_label": "s",
            "source_nreg": None,
            "evidence_artifact_id": None,
            "scope_status": "VARIANT_SCOPE_NOT_OBSERVABLE",
            "affects": [{
                "variant_id": None,
                "affected_component_scope": "NOT_IDENTIFIED",
                "component_description": "d",
                "before_variant_version_id": None,
                "after_variant_version_id": None,
                "scope_basis": None}]}],
        "extension_mappings": []}


class TestFilingRoundTrip(unittest.TestCase):
    def test_decompose_reconstruct_byte_stable(self):
        fx = mini_filing()
        rows = tables.filing_rows(fx)
        recon = tables.filing_from_rows(
            rows["filing"][0], rows["filing_version"],
            rows["submission_variant"], rows["variant_version"],
            rows["view_resolution"], rows["version_event"],
            rows["event_affects"], rows["artifact"], [])
        self.assertEqual(canonical_bytes(recon), canonical_bytes(fx))

    def test_extras_overlay(self):
        fx = dict(mini_filing(), custom_field={"b": 1})
        rows = tables.filing_rows(fx)
        self.assertEqual(json.loads(rows["filing"][0]["extras_json"]),
                         {"custom_field": {"b": 1}})
        recon = tables.filing_from_rows(
            rows["filing"][0], rows["filing_version"],
            rows["submission_variant"], rows["variant_version"],
            rows["view_resolution"], rows["version_event"],
            rows["event_affects"], rows["artifact"], [])
        self.assertEqual(canonical_bytes(recon), canonical_bytes(fx))


class TestFactRoundTrip(unittest.TestCase):
    REC = {
        "concept": "http://ns#C", "value_sha256": "AB" * 32,
        "value_len": 8, "value_preview": "98000000",
        "xValue_sha256": "CD" * 32, "xValue_len": 8,
        "xValue_preview": "98000000", "isNil": False,
        "decimals": "-6", "contextID": "c1", "unitID": "u1",
        "lang": "es", "concept_type": "http://ns#monetary",
        "is_numeric": True, "value_full": "98000000",
        "xValue_full": "98000000", "ns_kind": "taxonomy",
        "entity_scheme": "http://s", "entity": "E",
        "period_start": "2024-01-01", "period_end": "2024-06-30",
        "dimensions": {
            "http://ns#AxisA": "E:http://ns#MemberA",
            "http://ns#AxisB": "T:typed-value"},
        "unit": "http://u#EUR/http://u#shares",
        "_profile": "esef"}

    def test_row_round_trip(self):
        row, dims = tables.fact_rows(dict(self.REC), "v#v1", "S", 0, "f0")
        recon = tables.record_from_row(row, dims)
        expected = dict(self.REC)
        del expected["_profile"]
        self.assertEqual(
            json.dumps(recon, sort_keys=True),
            json.dumps(expected, sort_keys=True))
        self.assertEqual(row["unit_numerator"], "http://u#EUR")
        self.assertEqual(row["unit_denominator"], "http://u#shares")
        self.assertEqual(row["explicit_dim_count"], 1)
        self.assertEqual(row["typed_dim_count"], 1)

    def test_ipp_profile_drops_esef_keys(self):
        rec = {k: v for k, v in self.REC.items()
               if k not in ("concept_type", "is_numeric", "value_full",
                            "xValue_full", "ns_kind", "_profile")}
        row, dims = tables.fact_rows(dict(rec, _profile="ipp"),
                                     "v#v1", "S", 0, "f0")
        recon = tables.record_from_row(row, dims)
        self.assertEqual(json.dumps(recon, sort_keys=True),
                         json.dumps(rec, sort_keys=True))


class TestParquetDeterminism(unittest.TestCase):
    def test_byte_identical_writes(self):
        rows = [{"filing_id": "b", "issuer_denomination": "B",
                 "issuer_nif": None, "issuer_lei": "L",
                 "registro_oficial": "2", "family": "IPP",
                 "period_end": "2024-06-30", "extras_json": None},
                {"filing_id": "a", "issuer_denomination": "A",
                 "issuer_nif": "N", "issuer_lei": None,
                 "registro_oficial": "1", "family": "ESEF_IFA",
                 "period_end": "31/12/2024", "extras_json": '{"x":1}'}]
        with tempfile.TemporaryDirectory() as td:
            m1 = parquetio.write_table("filing", rows, Path(td) / "a.parquet")
            m2 = parquetio.write_table("filing", rows, Path(td) / "b.parquet")
            self.assertEqual(m1["sha256"], m2["sha256"])
            self.assertEqual(parquetio.read_table(Path(td) / "a.parquet"),
                             rows)

    def test_manifest_verify_detects_mutation(self):
        rows = [{"filing_id": "a", "issuer_denomination": "A",
                 "issuer_nif": None, "issuer_lei": None,
                 "registro_oficial": "1", "family": "IPP",
                 "period_end": "x", "extras_json": None}]
        with tempfile.TemporaryDirectory() as td:
            meta = {"filing": parquetio.write_table(
                "filing", rows, Path(td) / "filing.parquet")}
            man = manifest.build_manifest(
                inputs={}, tables=meta, code_commit="t",
                generator={}, params={})
            self.assertEqual(manifest.verify_manifest(td, man), [])
            p = Path(td) / "filing.parquet"
            b = bytearray(p.read_bytes())
            b[10] ^= 0xFF
            p.write_bytes(bytes(b))
            self.assertTrue(manifest.verify_manifest(td, man))


class TestIntegrity(unittest.TestCase):
    def test_clean_dataset(self):
        rows = tables.filing_rows(mini_filing())
        row, dims = tables.fact_rows(
            dict(TestFactRoundTrip.REC, _profile="esef"),
            "cnmv:ifa:1#es#v1", "S", 0, "f0")
        tbl = {t: rows.get(t, []) for t in schema.TABLE_ORDER}
        tbl["facts"] = [row]
        tbl["fact_dimension"] = dims
        self.assertEqual(integrity.check(tbl), [])

    def test_orphan_fact_detected(self):
        tbl: dict[str, list[dict]] = {t: [] for t in schema.TABLE_ORDER}
        row, dims = tables.fact_rows(
            dict(TestFactRoundTrip.REC, _profile="esef"),
            "missing#v1", "S", 0, "f0")
        tbl["facts"] = [row]
        tbl["fact_dimension"] = dims
        errs = integrity.check(tbl)
        self.assertTrue(any("facts.variant_version_id" in e for e in errs))

    def test_row_removal_detected(self):
        rows = tables.filing_rows(mini_filing())
        tbl = {t: rows.get(t, []) for t in schema.TABLE_ORDER}
        tbl["filing_version"].pop()
        errs = integrity.check(tbl)
        self.assertTrue(errs)
        # also: dropping a variant_version orphans facts + artifacts
        tbl = {t: rows.get(t, []) for t in schema.TABLE_ORDER}
        tbl["variant_version"].pop()
        self.assertTrue(integrity.check(tbl))


if __name__ == "__main__":
    unittest.main()
