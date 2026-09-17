"""Version-event query surface.

`source_label` is raw evidence text (CNMV), never an authoritative
classification — `event_type`/`scope_status`/`affects` carry the
canonical semantics.
"""
from __future__ import annotations

from opencnmv.query.dataset import Dataset, resolve_filing_id


def filing_events(ds: Dataset, ref: str | None = None) -> list[dict]:
    where, params = "", []
    if ref:
        where = "WHERE ve.filing_id = ?"
        params = [resolve_filing_id(ds, ref)]
    events = ds.sql(
        f"SELECT ve.* FROM version_event ve {where} "
        "ORDER BY ve.event_id", params)
    ev_ids = [e["event_id"] for e in events]
    affects = ds.sql(
        "SELECT * FROM event_affects WHERE event_id IN "
        f"({','.join('?' for _ in ev_ids)}) ORDER BY event_id, "
        "affects_ordinal", ev_ids) if ev_ids else []
    by_ev: dict[str, list[dict]] = {}
    for a in affects:
        by_ev.setdefault(a["event_id"], []).append(a)
    return [{
        "event_id": e["event_id"], "filing_id": e["filing_id"],
        "event_date": e["event_date"], "event_type": e["event_type"],
        "source_label": e["source_label"],
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
            for a in by_ev.get(e["event_id"], [])]}
        for e in events]
