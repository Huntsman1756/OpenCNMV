"""Provenance tracing: canonical row -> variant_version -> artifacts
-> pinned source evidence (sha256 + repo-relative evidence_path).

`evidence_path` values in the dataset are already repo-relative pinned
locators; this module never emits machine-specific absolute paths.
"""
from __future__ import annotations

from opencnmv.query.dataset import Dataset, resolve_fact_id


def _prov_rows(ds: Dataset, where: str, params: list) -> list[dict]:
    return ds.sql(f"SELECT * FROM provenance WHERE {where} "
                  "ORDER BY state_id, artifact_id, role", params)


def _chain(ds: Dataset, p: dict) -> dict:
    """One provenance row resolved to its canonical context chain."""
    vv = ds.sql("SELECT * FROM variant_version "
                "WHERE variant_version_id = ?",
                [p["variant_version_id"]])
    ctx = {"filing_id": p["filing_id"],
           "variant_version_id": p["variant_version_id"],
           "state_id": p["state_id"]}
    if vv:
        ctx["variant_id"] = vv[0]["variant_id"]
        ctx["version_seq"] = vv[0]["version_seq"]
        ctx["observed"] = vv[0]["observed"]
        ctx["created_by_event_id"] = vv[0]["created_by_event_id"]
        ctx["artifact_set_id"] = vv[0]["artifact_set_id"]
    return {"role": p["role"], "context": ctx,
            "source_artifact": {
                "artifact_id": p["artifact_id"],
                "sha256": p["sha256"], "byte_size": p["byte_size"],
                "media_type": p["media_type"],
                "source_url": p["source_url"],
                "resolved_url": p["resolved_url"],
                "retrieved_at": p["retrieved_at"],
                "http_status": p["http_status"],
                "evidence_path": p["evidence_path"]},
            "parse": {"arelle_version": p["arelle_version"],
                      "lexical_shim": p["lexical_shim"]}}


def fact_provenance(ds: Dataset, fact_ref: str) -> dict:
    fid = resolve_fact_id(ds, fact_ref)
    fact = ds.sql("SELECT * FROM facts WHERE fact_id = ?", [fid])[0]
    rows = _prov_rows(ds, "state_id = ?", [fact["state_id"]])
    return {"fact_id": fid,
            "structural_identity": {
                "concept": fact["concept"], "entity": fact["entity"],
                "period_start": fact["period_start"],
                "period_end": fact["period_end"],
                "period_instant": fact["period_instant"],
                "period_forever": fact["period_forever"],
                "unit": fact["unit"], "lang": fact["lang"],
                "canonical_dims_json": fact["canonical_dims_json"]},
            "provenance": [_chain(ds, p) for p in rows]}


def artifact_provenance(ds: Dataset, artifact_ref: str) -> dict:
    """artifact_ref = sha256:<hex> | bare <hex>."""
    aid = artifact_ref if artifact_ref.startswith("sha256:") \
        else f"sha256:{artifact_ref}"
    rows = ds.sql("SELECT * FROM artifact WHERE artifact_id = ?",
                  [aid])
    prov = _prov_rows(ds, "artifact_id = ?", [aid])
    if not rows and not prov:
        from opencnmv.query.errors import NotFoundError
        raise NotFoundError(f"no artifact {aid!r}")
    return {"artifact_id": aid,
            "artifact_rows": rows,
            "provenance": [_chain(ds, p) for p in prov]}


def variant_version_provenance(ds: Dataset, vv_ref: str) -> dict:
    rows = _prov_rows(ds, "variant_version_id = ?", [vv_ref])
    if not rows:
        vv = ds.sql("SELECT variant_version_id FROM variant_version "
                    "WHERE variant_version_id = ?", [vv_ref])
        if not vv:
            from opencnmv.query.errors import NotFoundError
            raise NotFoundError(f"no variant_version {vv_ref!r}")
    return {"variant_version_id": vv_ref,
            "provenance": [_chain(ds, p) for p in rows]}


def state_provenance(ds: Dataset, state_id: str) -> dict:
    """All provenance links recorded for one frozen corpus state."""
    rows = _prov_rows(ds, "state_id = ?", [state_id])
    if not rows:
        from opencnmv.query.errors import NotFoundError
        raise NotFoundError(f"no provenance for state {state_id!r}")
    return {"state_id": state_id,
            "provenance": [_chain(ds, p) for p in rows]}
