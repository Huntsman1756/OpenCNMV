"""Logical integrity for a COLUMNAR_DATASET_V1 row set.

Parquet does not enforce foreign keys; this module enforces them
logically over the table row lists (pre-write or post-read). ``check``
returns a list of violations — empty means the dataset is consistent.

Rules enforced:
  * primary identities unique (filing_id, filing_version_id, variant_id,
    variant_version_id, event_id, state_id, fact_id, ...)
  * every non-null foreign reference resolves to an existing row
  * observed variant_versions carry artifact_set_id; unobserved do not
  * no variant/version is marked preferred/canonical (no such column
    exists by schema — asserted structurally)
"""
from __future__ import annotations


def _dupes(rows: list[dict], key) -> list:
    seen: dict = {}
    out = []
    for r in rows:
        k = key(r)
        if k in seen:
            out.append(k)
        seen[k] = r
    return out


def _ids(rows: list[dict], col: str) -> set:
    return {r[col] for r in rows}


def check(tables: dict[str, list[dict]]) -> list[str]:
    """tables: {table_name: [row,...]}. Returns [] when consistent."""
    err: list[str] = []
    t = {n: tables.get(n, []) for n in
         ("filing", "filing_version", "submission_variant",
          "variant_version", "view_resolution", "version_event",
          "event_affects", "artifact", "extension_mapping", "provenance",
          "facts", "fact_dimension")}

    # --- primary identities ---
    pk = {
        "filing": lambda r: r["filing_id"],
        "filing_version": lambda r: r["filing_version_id"],
        "submission_variant": lambda r: r["variant_id"],
        "variant_version": lambda r: r["variant_version_id"],
        "version_event": lambda r: r["event_id"],
        "provenance": lambda r: r["state_id"],
        "facts": lambda r: r["fact_id"],
        "fact_dimension": lambda r: (r["fact_id"], r["dim_qname"]),
        "artifact": lambda r: (r["owner_kind"], r["owner_id"],
                               r["artifact_ordinal"]),
        "event_affects": lambda r: (r["event_id"], r["affects_ordinal"]),
        "view_resolution": lambda r: (r["filing_id"],
                                      r["requested_ui_language"]),
        "extension_mapping": lambda r: (r["filing_id"], r["source_file"],
                                        r["source_ordinal"]),
    }
    for name, key in pk.items():
        for d in _dupes(t[name], key):
            err.append(f"{name}: duplicate primary identity {d!r}")

    filing_ids = _ids(t["filing"], "filing_id")
    fv_ids = _ids(t["filing_version"], "filing_version_id")
    var_ids = _ids(t["submission_variant"], "variant_id")
    vv_ids = _ids(t["variant_version"], "variant_version_id")
    ev_ids = _ids(t["version_event"], "event_id")
    fact_ids = _ids(t["facts"], "fact_id")
    art_ids = {r["artifact_id"] for r in t["artifact"]}

    def fk(table, col, targets, label, null_ok=True):
        for r in t[table]:
            v = r[col]
            if v is None and null_ok:
                continue
            if v not in targets:
                err.append(f"{table}.{col}: {v!r} not in {label}")

    # --- foreign references ---
    fk("filing_version", "filing_id", filing_ids, "filing")
    fk("submission_variant", "filing_id", filing_ids, "filing")
    fk("variant_version", "variant_id", var_ids, "submission_variant",
       null_ok=False)
    fk("variant_version", "created_by_event_id", ev_ids, "version_event")
    fk("variant_version", "supersedes_variant_version_id", vv_ids,
       "variant_version")
    fk("view_resolution", "filing_id", filing_ids, "filing", null_ok=False)
    fk("view_resolution", "resolved_variant_id", var_ids,
       "submission_variant", null_ok=False)
    fk("version_event", "filing_id", filing_ids, "filing", null_ok=False)
    fk("version_event", "evidence_artifact_id", art_ids, "artifact")
    fk("event_affects", "event_id", ev_ids, "version_event", null_ok=False)
    fk("event_affects", "variant_id", var_ids, "submission_variant")
    fk("event_affects", "before_variant_version_id", vv_ids,
       "variant_version")
    fk("event_affects", "after_variant_version_id", vv_ids,
       "variant_version")
    fk("extension_mapping", "filing_id", filing_ids, "filing",
       null_ok=False)
    fk("extension_mapping", "source_variant_id", var_ids,
       "submission_variant")
    fk("extension_mapping", "target_variant_id", var_ids,
       "submission_variant")
    fk("facts", "variant_version_id", vv_ids, "variant_version",
       null_ok=False)
    fk("fact_dimension", "fact_id", fact_ids, "facts", null_ok=False)
    fk("provenance", "filing_id", filing_ids, "filing", null_ok=False)
    fk("provenance", "variant_version_id", vv_ids, "variant_version")
    fk("provenance", "artifact_id", art_ids, "artifact")

    # --- polymorphic artifact ownership ---
    for r in t["artifact"]:
        ok = (r["owner_kind"] == "variant_version" and
              r["owner_id"] in vv_ids) or \
             (r["owner_kind"] == "filing_version" and
              r["owner_id"] in fv_ids) or \
             (r["owner_kind"] == "version_event" and
              r["owner_id"] in ev_ids)
        if not ok:
            err.append(f"artifact: unresolved owner "
                       f"{r['owner_kind']}:{r['owner_id']!r}")

    # --- cardinality: a filing always has >=1 version and >=1 variant;
    #     every variant has >=1 variant_version ---
    fv_filing_ids = _ids(t["filing_version"], "filing_id")
    sv_filing_ids = _ids(t["submission_variant"], "filing_id")
    for fid in filing_ids:
        if fid not in fv_filing_ids:
            err.append(f"filing {fid!r}: no filing_version row")
        if fid not in sv_filing_ids:
            err.append(f"filing {fid!r}: no submission_variant row")
    vv_variant_ids = _ids(t["variant_version"], "variant_id")
    for vid in var_ids:
        if vid not in vv_variant_ids:
            err.append(f"submission_variant {vid!r}: no variant_version row")

    # --- model invariants ---
    for vv in t["variant_version"]:
        if vv["observed"] and not vv["artifact_set_id"]:
            err.append(f"variant_version {vv['variant_version_id']}: "
                       f"observed without artifact_set_id")
        if not vv["observed"] and vv["artifact_set_id"]:
            err.append(f"variant_version {vv['variant_version_id']}: "
                       f"unobserved with artifact_set_id")

    # no 'preferred/canonical/truth' marker may exist on variants
    bad_cols = [c for c in t["submission_variant"][0]
                if c in ("preferred", "canonical", "is_truth")] \
        if t["submission_variant"] else []
    for c in bad_cols:
        err.append(f"submission_variant: forbidden column {c!r}")

    return err
