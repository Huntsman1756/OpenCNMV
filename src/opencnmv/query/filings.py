"""Filing discovery and canonical filing detail over a Dataset."""
from __future__ import annotations

from opencnmv.dataset import tables as dtables
from opencnmv.query.dataset import Dataset, resolve_filing_id
from opencnmv.query.errors import NotFoundError


def iso_date(d: str | None) -> str | None:
    """Normalise 'dd/mm/yyyy' or ISO 'yyyy-mm-dd' to ISO. None stays None."""
    if not d:
        return None
    if "/" in d:
        p = d.split("/")
        if len(p) == 3 and all(x.isdigit() for x in p):
            return f"{p[2]}-{p[1].zfill(2)}-{p[0].zfill(2)}"
        return None
    return d


def list_filings(ds: Dataset, *, issuer: str | None = None,
                 nif: str | None = None, lei: str | None = None,
                 family: str | None = None, period: str | None = None,
                 date_from: str | None = None,
                 date_to: str | None = None) -> list[dict]:
    """Deterministic filing list. period/from/to compare period_end
    normalised to ISO (the corpus mixes 'dd/mm/yyyy' and ISO)."""
    rows = ds.sql(
        "SELECT f.filing_id, f.issuer_denomination, f.issuer_nif, "
        "       f.issuer_lei, f.registro_oficial, f.family, f.period_end, "
        "       (SELECT count(*) FROM submission_variant sv "
        "         WHERE sv.filing_id = f.filing_id) AS variants, "
        "       (SELECT count(*) FROM variant_version vv "
        "         WHERE vv.variant_id IN (SELECT variant_id FROM "
        "           submission_variant s2 WHERE s2.filing_id = f.filing_id))"
        "       AS variant_versions, "
        "       (SELECT count(*) FROM facts ft "
        "         WHERE ft.variant_version_id IN (SELECT variant_version_id"
        "           FROM variant_version v2 WHERE v2.variant_id IN "
        "           (SELECT variant_id FROM submission_variant s3 "
        "            WHERE s3.filing_id = f.filing_id))) AS facts "
        "FROM filing f ORDER BY f.filing_id")
    out = []
    p_norm = iso_date(period) if period else None
    f_norm = iso_date(date_from) if date_from else None
    t_norm = iso_date(date_to) if date_to else None
    for r in rows:
        iso = iso_date(r["period_end"])
        if issuer and issuer.lower() not in \
                (r["issuer_denomination"] or "").lower():
            continue
        if nif and r["issuer_nif"] != nif:
            continue
        if lei and (r["issuer_lei"] or "").upper() != lei.upper():
            continue
        if family and r["family"] != family:
            continue
        if p_norm and iso != p_norm:
            continue
        if f_norm and (iso is None or iso < f_norm):
            continue
        if t_norm and (iso is None or iso > t_norm):
            continue
        r["period_end_iso"] = iso
        out.append(r)
    return out


def filing_detail(ds: Dataset, ref: str) -> dict:
    """Reassemble the complete canonical filing object plus per-state
    provenance/fact-count summary. Nothing is flattened away."""
    fid = resolve_filing_id(ds, ref)
    frow = ds.sql("SELECT * FROM filing WHERE filing_id = ?", [fid])[0]
    fv = ds.sql("SELECT * FROM filing_version WHERE filing_id = ?", [fid])
    sv = ds.sql("SELECT * FROM submission_variant WHERE filing_id = ?",
                [fid])
    vv = ds.sql("SELECT * FROM variant_version WHERE variant_id IN "
                "(SELECT variant_id FROM submission_variant "
                " WHERE filing_id = ?)", [fid])
    vr = ds.sql("SELECT * FROM view_resolution WHERE filing_id = ?", [fid])
    ev = ds.sql("SELECT * FROM version_event WHERE filing_id = ?", [fid])
    af = ds.sql("SELECT * FROM event_affects WHERE event_id IN "
                "(SELECT event_id FROM version_event WHERE filing_id = ?)",
                [fid])
    owner_ids = ([r["filing_version_id"] for r in fv]
                 + [r["variant_version_id"] for r in vv]
                 + [r["event_id"] for r in ev])
    art = ds.sql("SELECT * FROM artifact WHERE owner_id IN "
                 f"({','.join('?' for _ in owner_ids)})", owner_ids) \
        if owner_ids else []
    mp = ds.sql("SELECT * FROM extension_mapping WHERE filing_id = ?",
                [fid])
    fx = dtables.filing_from_rows(
        frow, fv, sv, vv, vr, ev, af,
        [a for a in art if a["owner_kind"] != "version_event"], mp)
    prov = ds.sql("SELECT * FROM provenance WHERE filing_id = ? "
                  "ORDER BY state_id", [fid])
    fact_counts = {r["variant_version_id"]: r["n"] for r in ds.sql(
        "SELECT variant_version_id, count(*) AS n FROM facts "
        "WHERE variant_version_id IN "
        "(SELECT variant_version_id FROM variant_version "
        " WHERE variant_id IN (SELECT variant_id FROM submission_variant"
        "  WHERE filing_id = ?)) GROUP BY variant_version_id", [fid])}
    states = []
    for p in prov:
        states.append({k: p[k] for k in (
            "state_id", "variant_version_id", "artifact_id", "role",
            "sha256", "byte_size", "media_type", "source_url",
            "resolved_url", "retrieved_at", "http_status",
            "evidence_path", "arelle_version", "lexical_shim")})
        states[-1]["fact_count"] = fact_counts.get(
            p["variant_version_id"], 0)
    mapping_summary: dict[str, int] = {}
    for m in mp:
        mapping_summary[m["verdict"]] = \
            mapping_summary.get(m["verdict"], 0) + 1
    return {"filing": fx,
            "event_artifacts": [
                {"event_id": a["owner_id"],
                 "artifact_id": a["artifact_id"], "role": a["role"],
                 "sha256": a["sha256"], "media_type": a["media_type"]}
                for a in art if a["owner_kind"] == "version_event"],
            "states": states,
            "extension_mapping_summary": mapping_summary or None}


def variant_version_facts_count(ds: Dataset, vvid: str) -> int:
    return ds.sql("SELECT count(*) AS n FROM facts "
                  "WHERE variant_version_id = ?", [vvid])[0]["n"]


def require_variant_version(ds: Dataset, vvid: str) -> dict:
    hit = ds.sql("SELECT * FROM variant_version "
                 "WHERE variant_version_id = ?", [vvid])
    if not hit:
        raise NotFoundError(f"no variant_version {vvid!r}")
    return hit[0]
