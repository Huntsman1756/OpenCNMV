"""Unit tests for opencnmv.update (G2-D incremental update engine).

Self-contained: builds a tiny materialized dataset in a temp dir and
exercises the full plan -> apply cycle — transition vocabulary,
idempotent replay, stale-base control, failure injection, supersession
chains, conflict classification, and update invariants. No gate code,
no frozen evidence.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opencnmv.dataset import manifest, parquetio, schema as dschema, tables
from opencnmv.serialize import write_canonical
from opencnmv.update import apply as uapply
from opencnmv.update import delta as udelta
from opencnmv.update import integrity as uint
from opencnmv.update import observe as uobs
from opencnmv.update import transitions as T

FID = "cnmv:ifa:1"
VID_ES = FID + "#es"
VV1 = VID_ES + "#v1"


def mini_filing() -> dict:
    """One filing, one es variant v1, both-language view resolutions."""
    return {
        "filing_id": FID,
        "issuer": {"denomination": "X, S.A.", "lei": "L"},
        "registro_oficial": "1",
        "family": "ESEF_IFA",
        "period_end": "31/12/2024",
        "filing_versions": [{
            "filing_version_id": FID + "#nreg:9",
            "source_nreg": "9", "filed_at": "2025-02-01",
            "submission_kind": "ORIGINAL_SUBMISSION"}],
        "submission_variants": [
            {"variant_id": VID_ES, "filing_id": FID,
             "submission_language": "es",
             "variant_versions": [{
                 "variant_version_id": VV1,
                 "variant_id": VID_ES, "observed": True,
                 "artifact_set_id": "aa",
                 "artifacts": [{
                     "artifact_id": "sha256:" + "a1" * 32,
                     "role": "ESEF_PACKAGE_ZIP_XBRL",
                     "sha256": "a1" * 32, "bytes": 1,
                     "media_type": "application/zip",
                     "package_lang_tag": "es"}],
                 "created_by_event_id": None,
                 "supersedes_variant_version_id": None}]}],
        "view_resolutions": [
            {"requested_ui_language": "es",
             "resolved_variant_id": VID_ES,
             "resolution_mode": "SUBMITTED_VARIANT"},
            {"requested_ui_language": "en",
             "resolved_variant_id": VID_ES,
             "resolution_mode": "FALLBACK_TO_ES"}],
        "version_events": [],
        "extension_mappings": []}


def fact_rec(sha: str = "ab" * 32, n: int = 0) -> dict:
    return {
        "concept": "http://ns#C", "contextID": f"c{n}",
        "decimals": "-6", "dimensions": {}, "entity": "E",
        "entity_scheme": "http://s", "isNil": False, "lang": "es",
        "period_instant": "2024-12-31", "unitID": "u1",
        "value_len": 8, "value_preview": "98000000",
        "value_sha256": sha,
        "xValue_len": 8, "xValue_preview": "98000000",
        "xValue_sha256": "cd" * 32, "concept_type": "http://ns#mon",
        "is_numeric": True, "value_full": "98000000",
        "xValue_full": "98000000", "ns_kind": "taxonomy",
        "unit": "http://u#EUR", "_profile": "esef"}


def prov_row(state_id: str, vvid: str) -> dict:
    return {"state_id": state_id, "filing_id": FID,
            "variant_version_id": vvid,
            "artifact_id": "sha256:" + "a1" * 32,
            "role": "ESEF_PACKAGE_ZIP_XBRL", "sha256": "a1" * 32,
            "byte_size": 1, "media_type": "application/zip",
            "source_url": None, "resolved_url": None,
            "retrieved_at": None, "http_status": None,
            "evidence_path": "ev/x.zip",
            "arelle_version": "2.44.0", "lexical_shim": False}


def base_tables() -> dict[str, list[dict]]:
    """S0 row set: mini filing + one parsed state."""
    rows = tables.filing_rows(mini_filing())
    recs = [fact_rec(n=0), fact_rec(n=1)]
    seq_rows, dim_rows = [], []
    for seq, rec in enumerate(recs):
        row, dims = tables.fact_rows(rec, VV1, "S0", seq, f"cnmv:fact:{seq}")
        seq_rows.append(row)
        dim_rows.extend(dims)
    rows["facts"] = seq_rows
    rows["fact_dimension"] = dim_rows
    rows["provenance"] = [prov_row("S0", VV1)]
    return rows


def write_dataset(ds: Path, tbl: dict[str, list[dict]]) -> dict:
    ds.mkdir(parents=True)
    meta = {}
    for t in dschema.TABLE_ORDER:
        rows = sorted(tbl[t], key=parquetio.ROW_ORDER[t])
        meta[t] = parquetio.write_table(t, rows, ds / f"{t}.parquet")
    (ds / "schema").mkdir(exist_ok=True)
    for t in dschema.TABLE_ORDER:
        write_canonical(dschema.schema_dict(t),
                        ds / "schema" / f"{t}.schema.json")
    man = manifest.build_manifest(
        inputs={}, tables=meta, code_commit="t",
        generator={"tool": "test"}, params={})
    write_canonical(man, ds / "dataset_manifest.json")
    return man


def obs_for(fx: dict, **kw) -> dict:
    fobs = {"filing": fx}
    fobs.update(kw)
    return {"observation_format": uobs.OBSERVATION_FORMAT,
            "observation_id": "obs:test", "captured_at": None,
            "filings": [fobs]}


def v2_filing() -> dict:
    """Same filing observed again with an es v2 superseding v1."""
    fx = mini_filing()
    fx["submission_variants"][0]["variant_versions"].append({
        "variant_version_id": VID_ES + "#v2",
        "variant_id": VID_ES, "observed": True,
        "artifact_set_id": "bb",
        "artifacts": [{
            "artifact_id": "sha256:" + "b2" * 32,
            "role": "ESEF_PACKAGE_ZIP_XBRL",
            "sha256": "b2" * 32, "bytes": 2,
            "media_type": "application/zip",
            "package_lang_tag": "es"}],
        "created_by_event_id": None,
        "supersedes_variant_version_id": VV1})
    return fx


class TestVocabulary(unittest.TestCase):
    def test_required_vocabulary(self):
        required = {
            "NO_CHANGE", "NEW_FILING", "NEW_FILING_VERSION",
            "NEW_SUBMISSION_VARIANT", "NEW_VARIANT_VERSION",
            "NEW_VERSION_EVENT", "VARIANT_SCOPED_VERSION_EVENT",
            "FILING_SCOPE_NOT_OBSERVABLE", "ARTIFACT_CHANGED",
            "ARTIFACT_ADDED", "ARTIFACT_REMOVED", "FACT_ADDED",
            "FACT_REMOVED", "FACT_PAYLOAD_CHANGED",
            "EXTENSION_MAPPING_ADDED", "EXTENSION_MAPPING_CHANGED",
            "SOURCE_STATE_CONFLICT", "UNRESOLVED",
            "VIEW_RESOLUTION_RECORDED"}
        self.assertTrue(required <= T.ALL)

    def test_unknown_transition_rejected(self):
        with self.assertRaises(AssertionError):
            T.transition("MADE_UP", FID)
        t = T.transition(T.NO_CHANGE, FID, z=1, a=2)
        self.assertEqual(list(t), ["transition", "filing_id", "a", "z"])


class TestPlanApply(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.ds = Path(self.td.name) / "v1"
        self.tables = base_tables()
        self.man = write_dataset(self.ds, self.tables)

    def tearDown(self):
        self.td.cleanup()

    def plan(self, obs, base_hash=None):
        cur = uapply.load_manifest(self.ds)["corpus_logical_sha256"]
        return udelta.plan(uapply.load_tables(self.ds), obs,
                           base_hash or cur)

    def test_no_change_replay(self):
        obs = obs_for(mini_filing())
        delta = self.plan(obs)
        kinds = {t["transition"] for t in delta["transitions"]}
        self.assertEqual(kinds, {T.NO_CHANGE})
        self.assertFalse(any(delta["rows_added"].values()))
        res = uapply.apply_delta(self.ds, delta)
        self.assertEqual(res["status"], "NO_CHANGE")

    def test_new_filing(self):
        fx2 = mini_filing()
        fx2["filing_id"] = "cnmv:ifa:2"
        fx2["registro_oficial"] = "2"
        fx2["filing_versions"][0]["filing_version_id"] = \
            "cnmv:ifa:2#nreg:9"
        for sv in fx2["submission_variants"]:
            sv["variant_id"] = "cnmv:ifa:2#es"
            sv["filing_id"] = "cnmv:ifa:2"
            for vv in sv["variant_versions"]:
                vv["variant_version_id"] = "cnmv:ifa:2#es#v1"
                vv["variant_id"] = "cnmv:ifa:2#es"
        for vr in fx2["view_resolutions"]:
            vr["resolved_variant_id"] = "cnmv:ifa:2#es"
        obs = obs_for(fx2)
        delta = self.plan(obs)
        kinds = {t["transition"] for t in delta["transitions"]}
        self.assertIn(T.NEW_FILING, kinds)
        self.assertIn(T.NEW_VARIANT_VERSION, kinds)
        self.assertIn(T.VIEW_RESOLUTION_RECORDED, kinds)
        self.assertEqual(len(delta["rows_added"]["filing"]), 1)
        res = uapply.apply_delta(self.ds, delta)
        self.assertEqual(res["status"], "APPLIED")
        # replay is a no-op
        delta2 = self.plan(obs)
        self.assertEqual({t["transition"] for t in delta2["transitions"]},
                         {T.NO_CHANGE})
        self.assertEqual(uapply.apply_delta(self.ds, delta2)["status"],
                         "NO_CHANGE")

    def test_new_variant_version_chain(self):
        obs = obs_for(v2_filing(), states=[{
            "state_id": "S1", "variant_version_id": VID_ES + "#v2",
            "profile": "esef",
            "facts": [fact_rec(n=0),
                      fact_rec(sha="ef" * 32, n=1)],
            "units": [{"num": [], "den": []}] * 2,
            "provenance": prov_row("S1", VID_ES + "#v2")}])
        delta = self.plan(obs)
        kinds = {t["transition"] for t in delta["transitions"]}
        self.assertIn(T.NEW_VARIANT_VERSION, kinds)
        self.assertIn(T.FACT_PAYLOAD_CHANGED, kinds)
        res = uapply.apply_delta(self.ds, delta)
        self.assertEqual(res["status"], "APPLIED")
        merged = uapply.load_tables(self.ds)
        vvs = [r for r in merged["variant_version"]
               if r["variant_id"] == VID_ES]
        self.assertEqual([r["version_seq"] for r in
                          sorted(vvs, key=lambda r: r["version_seq"])],
                         [1, 2])
        self.assertEqual(uint.check_update_invariants(merged), [])
        # both payload states retained
        self.assertEqual(len([r for r in merged["facts"]
                              if r["variant_version_id"] == VV1]), 2)
        self.assertEqual(len([r for r in merged["facts"]
                              if r["variant_version_id"]
                              == VID_ES + "#v2"]), 2)

    def test_stale_base_rejected(self):
        delta = self.plan(obs_for(v2_filing(), states=[{
            "state_id": "S1", "variant_version_id": VID_ES + "#v2",
            "facts": [fact_rec()], "units": [{"num": [], "den": []}],
            "provenance": prov_row("S1", VID_ES + "#v2")}]))
        # advance the base, then re-apply the old delta -> stale
        res = uapply.apply_delta(self.ds, delta)
        self.assertEqual(res["status"], "APPLIED")
        with self.assertRaises(uapply.StaleBaseError):
            uapply.apply_delta(self.ds, delta)
        # a dataset whose base differs must also refuse the delta
        other = base_tables()
        other["filing"].append({
            "filing_id": "cnmv:ifa:9", "issuer_denomination": "Y",
            "issuer_nif": None, "issuer_lei": None,
            "registro_oficial": "9", "family": "IPP",
            "period_end": "x", "extras_json": None})
        with tempfile.TemporaryDirectory() as td2:
            ds2 = Path(td2) / "v1"
            write_dataset(ds2, other)
            with self.assertRaises(uapply.StaleBaseError):
                uapply.apply_delta(ds2, delta)

    def test_tampered_delta_rejected(self):
        delta = self.plan(obs_for(v2_filing(), states=[{
            "state_id": "S1", "variant_version_id": VID_ES + "#v2",
            "facts": [fact_rec()], "units": [{"num": [], "den": []}],
            "provenance": prov_row("S1", VID_ES + "#v2")}]))
        bad = json.loads(json.dumps(delta))
        bad["rows_added"]["variant_version"][0]["observed"] = False
        with self.assertRaises(uapply.DeltaError):
            uapply.apply_delta(self.ds, bad)

    def test_failure_injection_keeps_base(self):
        before = {p.name: p.read_bytes()
                  for p in self.ds.glob("*.parquet")}
        delta = self.plan(obs_for(v2_filing(), states=[{
            "state_id": "S1", "variant_version_id": VID_ES + "#v2",
            "facts": [fact_rec()], "units": [{"num": [], "den": []}],
            "provenance": prov_row("S1", VID_ES + "#v2")}]))
        for hook in ("before_tables", "during_table:facts",
                     "before_publish"):
            with self.assertRaises(RuntimeError):
                uapply.apply_delta(self.ds, delta, fail_hook=hook)
            after = {p.name: p.read_bytes()
                     for p in self.ds.glob("*.parquet")}
            self.assertEqual(before, after, f"base mutated by {hook}")
            self.assertEqual(manifest.verify_manifest(self.ds, self.man),
                             [], f"manifest broken after {hook}")
            self.assertFalse(list(self.ds.parent.glob("*.staging-*")),
                             f"staging left after {hook}")

    def test_conflict_blocks_all_rows(self):
        fx = mini_filing()
        fx["filing_versions"][0]["filed_at"] = "2099-01-01"  # contradicts
        obs = obs_for(fx)
        delta = self.plan(obs)
        kinds = {t["transition"] for t in delta["transitions"]}
        self.assertIn(T.SOURCE_STATE_CONFLICT, kinds)
        self.assertTrue(delta["unresolved"])
        self.assertFalse(any(delta["rows_added"].values()))
        res = uapply.apply_delta(self.ds, delta)
        self.assertEqual(res["status"], "NO_CHANGE")

    def test_fallback_creates_no_variant(self):
        # the mini filing already resolves en->es; re-observe identical
        obs = obs_for(mini_filing())
        delta = self.plan(obs)
        kinds = {t["transition"] for t in delta["transitions"]}
        self.assertNotIn(T.NEW_SUBMISSION_VARIANT, kinds)
        # adding a NEW ui language resolution records a row, never a variant
        fx = mini_filing()
        fx["view_resolutions"].append({
            "requested_ui_language": "fr",
            "resolved_variant_id": VID_ES,
            "resolution_mode": "FALLBACK_TO_ES"})
        delta = self.plan(obs_for(fx))
        kinds = {t["transition"] for t in delta["transitions"]}
        self.assertIn(T.VIEW_RESOLUTION_RECORDED, kinds)
        self.assertNotIn(T.NEW_SUBMISSION_VARIANT, kinds)

    def test_observation_hash_stable(self):
        o1 = obs_for(mini_filing())
        o2 = json.loads(json.dumps(o1))
        o2["observation_id"] = "obs:other"
        o2["captured_at"] = "2030-01-01T00:00:00Z"
        self.assertEqual(uobs.observation_sha256(o1),
                         uobs.observation_sha256(o2))
        o2["filings"][0]["filing"]["registro_oficial"] = "7"
        self.assertNotEqual(uobs.observation_sha256(o1),
                            uobs.observation_sha256(o2))

    def test_corrupt_observation_rejected(self):
        obs = obs_for(mini_filing())
        obs["observation_sha256"] = "0" * 64
        with self.assertRaises(uobs.ObservationError):
            uobs.verify_self_consistency(obs)

    def test_unobservable_scope_event(self):
        fx = mini_filing()
        fx["version_events"].append({
            "event_id": FID + "#evt:u", "event_date": "2025-03-01",
            "event_type": "SUBSTITUTION", "source_label": "s",
            "source_nreg": None, "evidence_artifact_id": None,
            "scope_status": "VARIANT_SCOPE_NOT_OBSERVABLE",
            "affects": [{
                "variant_id": None,
                "affected_component_scope": "NOT_IDENTIFIED",
                "component_description": "d",
                "before_variant_version_id": None,
                "after_variant_version_id": None,
                "scope_basis": None}]})
        delta = self.plan(obs_for(fx))
        kinds = {t["transition"] for t in delta["transitions"]}
        self.assertIn(T.NEW_VERSION_EVENT, kinds)
        self.assertIn(T.FILING_SCOPE_NOT_OBSERVABLE, kinds)
        self.assertNotIn(T.NEW_VARIANT_VERSION, kinds)


class TestUpdateInvariants(unittest.TestCase):
    def test_chain_break_detected(self):
        tbl = {t: [] for t in dschema.TABLE_ORDER}
        tbl["variant_version"] = [
            {"variant_version_id": "v#v1", "variant_id": "v",
             "version_seq": 1, "supersedes_variant_version_id": None,
             "created_by_event_id": None},
            {"variant_version_id": "v#v3", "variant_id": "v",
             "version_seq": 3, "supersedes_variant_version_id": "v#v2",
             "created_by_event_id": None}]
        errs = uint.check_update_invariants(tbl)
        self.assertTrue(any("non-contiguous" in e for e in errs))
        # contiguous seqs but wrong supersedes target
        tbl["variant_version"][1]["version_seq"] = 2
        errs = uint.check_update_invariants(tbl)
        self.assertTrue(any("expected" in e for e in errs))

    def test_not_observable_scope_with_variant_flagged(self):
        tbl = {t: [] for t in dschema.TABLE_ORDER}
        tbl["version_event"] = [{
            "event_id": "e", "filing_id": "f",
            "scope_status": "VARIANT_SCOPE_NOT_OBSERVABLE"}]
        tbl["event_affects"] = [{"event_id": "e", "variant_id": "f#es"}]
        errs = uint.check_update_invariants(tbl)
        self.assertTrue(any("NOT_OBSERVABLE" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
