"""Update-level invariants, checked on the merged state before publish.

Complements dataset.integrity (FKs, PKs, cardinality) with the history
rules that make incremental evolution safe:

  * per variant, variant_versions form a contiguous chain
    v1..vN linked by supersedes_variant_version_id
  * only the earliest version lacks a supersedes link
  * a version created_by an event references an event of the same filing
  * event_affects variant scope is consistent with the event's
    scope_status (NOT_OBSERVABLE events never assert variant identity)
"""
from __future__ import annotations


def check_update_invariants(tables: dict[str, list[dict]]) -> list[str]:
    err: list[str] = []
    vv_by_variant: dict[str, list[dict]] = {}
    for r in tables["variant_version"]:
        vv_by_variant.setdefault(r["variant_id"], []).append(r)
    for vid, vvs in vv_by_variant.items():
        seqs = sorted(r["version_seq"] for r in vvs)
        if seqs != list(range(1, len(vvs) + 1)):
            err.append(f"{vid}: non-contiguous version_seq {seqs}")
        by_seq = {r["version_seq"]: r for r in vvs}
        for r in vvs:
            sup = r["supersedes_variant_version_id"]
            if r["version_seq"] == 1:
                if sup is not None:
                    err.append(f"{r['variant_version_id']}: v1 supersedes")
            else:
                want = by_seq.get(r["version_seq"] - 1)
                if want is None:
                    continue
                if sup != want["variant_version_id"]:
                    err.append(
                        f"{r['variant_version_id']}: supersedes {sup!r}, "
                        f"expected {want['variant_version_id']!r}")
        if len(vvs) != len(by_seq):
            err.append(f"{vid}: duplicate version_seq")
    ev_filing = {e["event_id"]: e["filing_id"]
                 for e in tables["version_event"]}
    for r in tables["variant_version"]:
        ev = r["created_by_event_id"]
        if ev and ev in ev_filing:
            fid = r["variant_id"].rsplit("#", 1)[0]
            if ev_filing[ev] != fid:
                err.append(f"{r['variant_version_id']}: created_by event "
                           f"{ev!r} belongs to another filing")
    scope_by_ev = {e["event_id"]: e["scope_status"]
                   for e in tables["version_event"]}
    for a in tables["event_affects"]:
        if a["variant_id"] and \
                scope_by_ev.get(a["event_id"]) == \
                "VARIANT_SCOPE_NOT_OBSERVABLE":
            err.append(f"{a['event_id']}: scope NOT_OBSERVABLE but "
                       f"affects asserts variant {a['variant_id']!r}")
    return err
