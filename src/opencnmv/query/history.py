"""Variant/version lifecycle + version events for a filing.

Makes the TEF 20484 lifecycle legible without flattening it:
#es one version; #en v1 (unobserved) -> v2 (observed, created by the
13/03 EN_ONLY_REPLACED event, affects only #en); the 28/02 event stays
VARIANT_SCOPE_NOT_OBSERVABLE and asserts no variant.
"""
from __future__ import annotations

from opencnmv.query.dataset import Dataset, resolve_filing_id


def filing_history(ds: Dataset, ref: str) -> dict:
    """ref = filing_id | registro_oficial | variant_id."""
    if ref.startswith("cnmv:") and "#" in ref:
        fid = ref.split("#", 1)[0]
        variants_filter = [ref]
        resolve_filing_id(ds, fid)
    else:
        fid = resolve_filing_id(ds, ref)
        variants_filter = None

    variants = ds.sql(
        "SELECT * FROM submission_variant WHERE filing_id = ? "
        "ORDER BY variant_ordinal, variant_id", [fid])
    if variants_filter:
        variants = [v for v in variants
                    if v["variant_id"] in variants_filter]
        if not variants:
            from opencnmv.query.errors import NotFoundError
            raise NotFoundError(f"no variant {ref!r} on filing {fid!r}")

    vvs = ds.sql(
        "SELECT * FROM variant_version WHERE variant_id IN "
        "(SELECT variant_id FROM submission_variant WHERE filing_id = ?) "
        "ORDER BY variant_id, version_seq", [fid])
    vv_by_variant: dict[str, list[dict]] = {}
    for r in vvs:
        vv_by_variant.setdefault(r["variant_id"], []).append(r)

    vrs = ds.sql("SELECT * FROM view_resolution WHERE filing_id = ? "
                 "ORDER BY ordinal", [fid])
    vr_by_variant: dict[str, list[dict]] = {}
    for r in vrs:
        vr_by_variant.setdefault(r["resolved_variant_id"], []).append(r)

    events = ds.sql("SELECT * FROM version_event WHERE filing_id = ? "
                    "ORDER BY event_id", [fid])
    ev_ids = [e["event_id"] for e in events]
    affects = ds.sql(
        "SELECT * FROM event_affects WHERE event_id IN "
        f"({','.join('?' for _ in ev_ids)}) ORDER BY event_id, "
        "affects_ordinal", ev_ids) if ev_ids else []
    af_by_ev: dict[str, list[dict]] = {}
    for a in affects:
        af_by_ev.setdefault(a["event_id"], []).append(a)

    art_counts = {r["owner_id"]: r["n"] for r in ds.sql(
        "SELECT owner_id, count(*) AS n FROM artifact "
        "WHERE owner_kind = 'variant_version' GROUP BY owner_id")}
    fact_counts = {r["variant_version_id"]: r["n"] for r in ds.sql(
        "SELECT variant_version_id, count(*) AS n FROM facts "
        "GROUP BY variant_version_id")}

    out_variants = []
    for v in variants:
        versions = []
        for r in vv_by_variant.get(v["variant_id"], []):
            versions.append({
                "variant_version_id": r["variant_version_id"],
                "version_seq": r["version_seq"],
                "observed": r["observed"],
                "artifact_set_id": r["artifact_set_id"],
                "created_by_event_id": r["created_by_event_id"],
                "supersedes_variant_version_id":
                    r["supersedes_variant_version_id"],
                "artifact_count":
                    art_counts.get(r["variant_version_id"], 0),
                "fact_count":
                    fact_counts.get(r["variant_version_id"], 0)})
        out_variants.append({
            "variant_id": v["variant_id"],
            "submission_language": v["submission_language"],
            "versions": versions,
            "view_resolutions": [
                {"requested_ui_language": r["requested_ui_language"],
                 "resolution_mode": r["resolution_mode"]}
                for r in vr_by_variant.get(v["variant_id"], [])]})

    out_events = [{
        "event_id": e["event_id"], "event_date": e["event_date"],
        "event_type": e["event_type"], "source_label": e["source_label"],
        "source_nreg": e["source_nreg"],
        "evidence_artifact_id": e["evidence_artifact_id"],
        "scope_status": e["scope_status"],
        "affects": [{
            "variant_id": a["variant_id"],
            "affected_component_scope": a["affected_component_scope"],
            "component_description": a["component_description"],
            "before_variant_version_id": a["before_variant_version_id"],
            "after_variant_version_id": a["after_variant_version_id"],
            "scope_basis": a["scope_basis"]}
            for a in af_by_ev.get(e["event_id"], [])]}
        for e in events]

    return {"filing_id": fid, "variants": out_variants,
            "version_events": out_events}
