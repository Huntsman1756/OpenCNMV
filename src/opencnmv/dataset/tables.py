"""Canonical objects <-> columnar rows (COLUMNAR_DATASET_V1).

Both directions are deterministic and lossless:

* ``filing_rows`` / ``filing_from_rows`` decompose/rebuild a
  CANONICAL_MODEL_V1 filing dict. List order is preserved by explicit
  ordinal columns, so reconstruction under ``serialize.canonical_bytes``
  is byte-stable.
* Non-schema fixture fields (Pydantic ``extra="allow"``) live in
  ``filing.extras_json`` as canonical JSON and overlay the table-derived
  object on reconstruction — a frozen fixture wins over derived content.
* ``extension_mapping`` rows are populated from the full G1-C record
  sets, which include UNMATCHED entries that have no schema-valid
  ExtensionMapping form (``pair_id`` is required); those stay table-only
  rows and remain unresolved.
* Fact records (the frozen ``facts.jsonl`` field set) decompose into one
  ``facts`` row + N ``fact_dimension`` rows. ``profile`` selects the
  record's key set on reconstruction (esef adds concept_type /
  is_numeric / value_full / xValue_full / ns_kind).
"""
from __future__ import annotations

import json
import re

from opencnmv.provenance.hashes import canon

SCHEMA_FILING_KEYS = ("filing_id", "issuer", "registro_oficial", "family",
                      "period_end", "filing_versions", "submission_variants",
                      "view_resolutions", "version_events",
                      "extension_mappings")


def _jdump(obj) -> str:
    """Compact JSON preserving field order (unlike hashes.canon which
    sorts keys — extras/record payloads must round-trip byte-exact)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def filing_rows(fx: dict, *, extras: dict | None = None) -> dict[str, list[dict]]:
    """Decompose one canonical filing dict into table rows."""
    issuer = fx["issuer"]
    if extras is None:
        extras = {k: v for k, v in fx.items() if k not in SCHEMA_FILING_KEYS}
    rows: dict[str, list[dict]] = {
        "filing": [{
            "filing_id": fx["filing_id"],
            "issuer_denomination": issuer["denomination"],
            "issuer_nif": issuer.get("nif"),
            "issuer_lei": issuer.get("lei"),
            "registro_oficial": fx["registro_oficial"],
            "family": fx["family"],
            "period_end": fx["period_end"],
            "extras_json": _jdump(extras) if extras else None}],
        "filing_version": [], "submission_variant": [],
        "variant_version": [], "view_resolution": [], "version_event": [],
        "event_affects": [], "artifact": [], "extension_mapping": []}
    for seq, fv in enumerate(fx.get("filing_versions", [])):
        rows["filing_version"].append({
            "filing_version_id": fv["filing_version_id"],
            "filing_id": fx["filing_id"],
            "source_nreg": fv.get("source_nreg"),
            "filed_at": fv.get("filed_at"),
            "submission_kind": fv.get("submission_kind"),
            "version_seq": seq})
        for i, a in enumerate(fv.get("artifacts", [])):
            rows["artifact"].append(_artifact_row(
                "filing_version", fv["filing_version_id"], i, a))
    for ord_, sv in enumerate(fx.get("submission_variants", [])):
        rows["submission_variant"].append({
            "variant_id": sv["variant_id"], "filing_id": sv["filing_id"],
            "submission_language": sv["submission_language"],
            "variant_ordinal": ord_})
        for vv in sv.get("variant_versions", []):
            rows["variant_version"].append({
                "variant_version_id": vv["variant_version_id"],
                "variant_id": vv["variant_id"],
                "version_seq": int(vv["variant_version_id"].rsplit("#v", 1)[1])
                if "#v" in vv["variant_version_id"] else 0,
                "observed": vv["observed"],
                "artifact_set_id": vv.get("artifact_set_id"),
                "created_by_event_id": vv.get("created_by_event_id"),
                "supersedes_variant_version_id":
                    vv.get("supersedes_variant_version_id")})
            for i, a in enumerate(vv.get("artifacts", [])):
                rows["artifact"].append(_artifact_row(
                    "variant_version", vv["variant_version_id"], i, a))
    for i, vr in enumerate(fx.get("view_resolutions", [])):
        rows["view_resolution"].append({
            "filing_id": fx["filing_id"],
            "requested_ui_language": vr["requested_ui_language"],
            "resolved_variant_id": vr["resolved_variant_id"],
            "resolution_mode": vr["resolution_mode"],
            "ordinal": i})
    for ev in fx.get("version_events", []):
        rows["version_event"].append({
            "event_id": ev["event_id"], "filing_id": fx["filing_id"],
            "event_date": ev.get("event_date"), "event_type": ev["event_type"],
            "source_label": ev.get("source_label"),
            "source_nreg": ev.get("source_nreg"),
            "evidence_artifact_id": ev.get("evidence_artifact_id"),
            "scope_status": ev["scope_status"]})
        for i, af in enumerate(ev.get("affects", [])):
            rows["event_affects"].append({
                "event_id": ev["event_id"], "affects_ordinal": i,
                "variant_id": af.get("variant_id"),
                "affected_component_scope": af["affected_component_scope"],
                "component_description": af.get("component_description"),
                "before_variant_version_id":
                    af.get("before_variant_version_id"),
                "after_variant_version_id": af.get("after_variant_version_id"),
                "scope_basis": af.get("scope_basis")})
    return rows


def mapping_rows(filing_id: str, source_lang: str, target_lang: str,
                 records: list[dict], source_file: str) -> list[dict]:
    """All G1-C mapping records for a filing -> extension_mapping rows."""
    from opencnmv.canonicalize import extension_mapping as xmap
    out = []
    for i, rec in enumerate(records):
        out.append({
            "filing_id": filing_id, "source_file": source_file,
            "source_ordinal": i,
            "pair_id": rec.get("pair_id"),
            "source_variant_id": f"{filing_id}#{source_lang}",
            "target_variant_id": f"{filing_id}#{target_lang}",
            "source_qname": rec["source_qname"],
            "target_qname": rec.get("target_qname"),
            "mapping_type": rec.get("mapping_type"),
            "verdict": rec["verdict"],
            "rewrites_identity": xmap.rewrites_identity(rec),
            "record_json": _jdump(rec)})
    return out


def _artifact_row(owner_kind: str, owner_id: str, i: int, a: dict) -> dict:
    return {"owner_kind": owner_kind, "owner_id": owner_id,
            "artifact_ordinal": i, "artifact_id": a["artifact_id"],
            "role": a["role"], "sha256": a["sha256"],
            "bytes": a.get("bytes"), "media_type": a.get("media_type"),
            "source_url": a.get("source_url"),
            "package_lang_tag": a.get("package_lang_tag")}


def _artifact_dict(r: dict) -> dict:
    a = {"artifact_id": r["artifact_id"], "role": r["role"],
         "sha256": r["sha256"]}
    for k in ("bytes", "media_type", "source_url"):
        if r[k] is not None:
            a[k] = r[k]
    a["package_lang_tag"] = r["package_lang_tag"]  # always emitted
    return a


def filing_from_rows(filing: dict, filing_versions: list[dict],
                     variants: list[dict], variant_versions: list[dict],
                     view_resolutions: list[dict], events: list[dict],
                     affects: list[dict], artifacts: list[dict],
                     mappings: list[dict]) -> dict:
    """Reassemble a canonical filing dict from table rows.

    Field order mirrors the canonical serialization layout so the result
    is byte-stable under ``serialize.canonical_bytes``.
    """
    issuer = {"denomination": filing["issuer_denomination"]}
    if filing["issuer_nif"] is not None:
        issuer["nif"] = filing["issuer_nif"]
    if filing["issuer_lei"] is not None:
        issuer["lei"] = filing["issuer_lei"]

    arts_by_owner: dict[str, list[dict]] = {}
    for a in artifacts:
        arts_by_owner.setdefault(a["owner_id"], []).append(a)
    for owned in arts_by_owner.values():
        owned.sort(key=lambda r: r["artifact_ordinal"])

    fx: dict = {
        "filing_id": filing["filing_id"], "issuer": issuer,
        "registro_oficial": filing["registro_oficial"],
        "family": filing["family"], "period_end": filing["period_end"],
        "filing_versions": [], "submission_variants": [],
        "view_resolutions": [], "version_events": [],
        "extension_mappings": []}

    for fv in sorted(filing_versions,
                     key=lambda r: (r["version_seq"],
                                    r["filing_version_id"])):
        d = {"filing_version_id": fv["filing_version_id"],
             "source_nreg": fv["source_nreg"], "filed_at": fv["filed_at"],
             "submission_kind": fv["submission_kind"]}
        owned_fv = arts_by_owner.get(fv["filing_version_id"])
        if owned_fv:
            d["artifacts"] = [_artifact_dict(a) for a in owned_fv]
        fx["filing_versions"].append(d)

    vv_by_variant: dict[str, list[dict]] = {}
    for vv in variant_versions:
        vv_by_variant.setdefault(vv["variant_id"], []).append(vv)
    for sv in sorted(variants, key=lambda r: (r["variant_ordinal"],
                                              r["variant_id"])):
        vvs = []
        for vv in sorted(vv_by_variant.get(sv["variant_id"], []),
                         key=lambda r: (r["version_seq"],
                                        r["variant_version_id"])):
            vvs.append({
                "variant_version_id": vv["variant_version_id"],
                "variant_id": vv["variant_id"], "observed": vv["observed"],
                "artifact_set_id": vv["artifact_set_id"],
                "artifacts": [_artifact_dict(a) for a in
                              arts_by_owner.get(vv["variant_version_id"],
                                                [])],
                "created_by_event_id": vv["created_by_event_id"],
                "supersedes_variant_version_id":
                    vv["supersedes_variant_version_id"]})
        fx["submission_variants"].append({
            "variant_id": sv["variant_id"], "filing_id": sv["filing_id"],
            "submission_language": sv["submission_language"],
            "variant_versions": vvs})

    for vr in sorted(view_resolutions,
                     key=lambda r: (r["ordinal"],
                                    r["requested_ui_language"])):
        fx["view_resolutions"].append({
            "requested_ui_language": vr["requested_ui_language"],
            "resolved_variant_id": vr["resolved_variant_id"],
            "resolution_mode": vr["resolution_mode"]})

    affects_by_event: dict[str, list[dict]] = {}
    for af in affects:
        affects_by_event.setdefault(af["event_id"], []).append(af)
    for ev in sorted(events, key=lambda r: r["event_id"]):
        af_rows = sorted(affects_by_event.get(ev["event_id"], []),
                         key=lambda r: r["affects_ordinal"])
        fx["version_events"].append({
            "event_id": ev["event_id"], "event_date": ev["event_date"],
            "event_type": ev["event_type"], "source_label": ev["source_label"],
            "source_nreg": ev["source_nreg"],
            "evidence_artifact_id": ev["evidence_artifact_id"],
            "scope_status": ev["scope_status"],
            "affects": [{
                "variant_id": a["variant_id"],
                "affected_component_scope": a["affected_component_scope"],
                "component_description": a["component_description"],
                "before_variant_version_id": a["before_variant_version_id"],
                "after_variant_version_id": a["after_variant_version_id"],
                "scope_basis": a["scope_basis"]} for a in af_rows]})

    for m in sorted(mappings, key=lambda r: (r["source_file"],
                                             r["source_ordinal"])):
        if m["pair_id"] is None:
            # UNMATCHED / unpaired records exist only as table rows — they
            # have no schema-valid ExtensionMapping form (pair_id required)
            continue
        fx["extension_mappings"].append({
            "pair_id": m["pair_id"], "filing_id": m["filing_id"],
            "source_variant_id": m["source_variant_id"],
            "target_variant_id": m["target_variant_id"],
            "source_qname": m["source_qname"],
            "target_qname": m["target_qname"],
            "mapping_type": m["mapping_type"], "verdict": m["verdict"],
            "evidence": (json.loads(m["record_json"]).get("evidence")
                         or [])})

    # extras overlay: frozen-fixture fields (fact_examples,
    # extension_mapping_summary, fixture-scoped extension_mappings) win.
    if filing["extras_json"]:
        fx.update(json.loads(filing["extras_json"]))
    return fx


# --- fact plane --------------------------------------------------------------

# Record keys written by canonicalize.facts.fact_record, per profile.
FACT_BASE_KEYS = ("concept", "value_sha256", "value_len", "value_preview",
                  "xValue_sha256", "xValue_len", "xValue_preview", "isNil",
                  "decimals", "contextID", "unitID", "lang")
FACT_ESEF_KEYS = ("concept_type", "is_numeric", "value_full", "xValue_full",
                  "ns_kind")


_UNIT_SEP = re.compile(r"(?<![:/])/(?=\w+://)")


def _unit_lists(sig: str | None) -> tuple[list[str], list[str]]:
    """Split a unit signature into numerator/denominator measures.

    The signature is num-measures '*' joined + '/' + den-measures '*'
    joined; each measure is a URI QName (``scheme://...#local``). The
    separator is the only '/' that is followed by a URI scheme and is not
    part of a '://'. When the corpus materializer runs, real measures are
    injected as ``_unit_num``/``_unit_den`` from the live Arelle model —
    this fallback exists only for records built without a model.
    """
    if not sig:
        return [], []
    if _UNIT_SEP.search(sig):
        num, den = _UNIT_SEP.split(sig, maxsplit=1)
    else:
        num, den = sig, ""
    return (num.split("*") if num else [],
            den.split("*") if den else [])


def fact_rows(rec: dict, variant_version_id: str, state_id: str,
              seq: int, fact_id: str,
              unit_measures: tuple[list, list] | None = None
              ) -> tuple[dict, list[dict]]:
    """One facts row + fact_dimension rows from a canonical fact record."""
    num: list = []
    den: list = []
    if unit_measures is not None:
        num, den = unit_measures
    elif rec.get("_unit_num") is not None:
        num, den = rec["_unit_num"], rec.get("_unit_den") or []
    else:
        num, den = _unit_lists(rec.get("unit"))
    dims_raw = rec.get("dimensions") or {}
    dims = []
    for dq, dv in sorted(dims_raw.items()):
        kind, _, val = dv.partition(":")
        dims.append({"fact_id": fact_id, "dim_qname": dq,
                     "dim_kind": kind,
                     "member_qname": val if kind == "E" else None,
                     "typed_value": val if kind == "T" else None})
    row = {"fact_id": fact_id, "variant_version_id": variant_version_id,
           "state_id": state_id, "seq": seq, "profile": rec["_profile"]}
    for k in FACT_BASE_KEYS + FACT_ESEF_KEYS:
        row[k] = rec.get(k)
    for k in ("entity_scheme", "entity", "period_start", "period_end",
              "period_instant", "unit"):
        row[k] = rec.get(k)
    row["period_forever"] = bool(rec.get("period_forever"))
    row["unit_numerator"] = "*".join(num) or None
    row["unit_denominator"] = "*".join(den) or None
    row["unit_numerator_count"] = len(num)
    row["unit_denominator_count"] = len(den)
    row["explicit_dim_count"] = sum(1 for d in dims if d["dim_kind"] == "E")
    row["typed_dim_count"] = sum(1 for d in dims if d["dim_kind"] == "T")
    row["canonical_dims_json"] = canon(dims_raw) if dims_raw else None
    return row, dims


def record_from_row(row: dict, dims: list[dict]) -> dict:
    """Rebuild the canonical fact record (facts.jsonl line object)."""
    rec = {k: row[k] for k in FACT_BASE_KEYS}
    if row["profile"] == "esef":
        for k in FACT_ESEF_KEYS:
            rec[k] = row[k]
    if row["entity_scheme"] is not None or row["entity"] is not None:
        rec["entity_scheme"] = row["entity_scheme"]
        rec["entity"] = row["entity"]
        if row["period_forever"]:
            rec["period_forever"] = True
        elif row["period_instant"] is not None:
            rec["period_instant"] = row["period_instant"]
        else:
            rec["period_start"] = row["period_start"]
            rec["period_end"] = row["period_end"]
        rec["dimensions"] = {d["dim_qname"]: (
            "E:" + (d["member_qname"] or "") if d["dim_kind"] == "E"
            else "T:" + (d["typed_value"] or ""))
            for d in dims}
    if row["unit"] is not None:
        rec["unit"] = row["unit"]
    return rec
