"""Fact query surface — bounded, multiset-preserving.

Fact identity is structural (concept | entity | period | dimensions |
unit | lang) PLUS variant_version; payload is separate. No query here
ever deduplicates by concept+period — duplicate facts under a structural
key remain distinct rows (fact_id carries a deterministic #occ suffix).
"""
from __future__ import annotations

from opencnmv.dataset import tables as dtables
from opencnmv.query.dataset import Dataset, resolve_fact_id, \
    resolve_filing_id, resolve_variant_id


DEFAULT_LIMIT = 100


def _like(s: str) -> str:
    """Literal substring -> LIKE pattern (escape wildcards)."""
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%") \
        .replace("_", "\\_") + "%"


def _fact_view(row: dict, dims: list[dict]) -> dict:
    """Complete machine-facing fact object: full canonical record fields
    + dataset identity + structured dimensions + complete unit."""
    rec = dtables.record_from_row(row, dims)
    out = {
        "fact_id": row["fact_id"],
        "state_id": row["state_id"],
        "variant_version_id": row["variant_version_id"],
        "seq": row["seq"],
        "profile": row["profile"],
        "concept": row["concept"],
        "entity_scheme": row["entity_scheme"],
        "entity": row["entity"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "period_instant": row["period_instant"],
        "period_forever": row["period_forever"],
        "contextID": row["contextID"],
        "unitID": row["unitID"],
        "unit": row["unit"],
        "unit_numerator": (row["unit_numerator"].split("*")
                           if row["unit_numerator"] else []),
        "unit_denominator": (row["unit_denominator"].split("*")
                             if row["unit_denominator"] else []),
        "lang": row["lang"],
        "decimals": row["decimals"],
        "isNil": row["isNil"],
        "value_sha256": row["value_sha256"],
        "value_len": row["value_len"],
        "value_preview": row["value_preview"],
        "value_full": row["value_full"],
        "xValue_sha256": row["xValue_sha256"],
        "xValue_preview": row["xValue_preview"],
        "xValue_full": row["xValue_full"],
        "concept_type": row["concept_type"],
        "is_numeric": row["is_numeric"],
        "ns_kind": row["ns_kind"],
        "dimensions": [{"dim_qname": d["dim_qname"],
                        "dim_kind": d["dim_kind"],
                        "member_qname": d["member_qname"],
                        "typed_value": d["typed_value"]}
                       for d in sorted(dims,
                                       key=lambda d: d["dim_qname"])],
        "canonical_record": rec,
    }
    return out


def _dims_for(ds: Dataset, fact_ids: list[str]) -> dict[str, list[dict]]:
    if not fact_ids:
        return {}
    rows = ds.sql(
        "SELECT * FROM fact_dimension WHERE fact_id IN "
        f"({','.join('?' for _ in fact_ids)}) "
        "ORDER BY fact_id, dim_qname", fact_ids)
    out: dict[str, list[dict]] = {}
    for d in rows:
        out.setdefault(d["fact_id"], []).append(d)
    return out


def query_facts(ds: Dataset, *, filing: str | None = None,
                variant: str | None = None, state: str | None = None,
                concept: str | None = None, period: str | None = None,
                lang: str | None = None, dims: str | None = None,
                unit: str | None = None, nil: bool = False,
                limit: int = DEFAULT_LIMIT,
                count_only: bool = False) -> dict:
    """Filtered fact query. Deterministic order (state_id, seq).

    Returns {"total": N, "limit": L, "truncated": bool, "facts": [...]}.
    """
    where: list[str] = []
    params: list = []
    join = ""
    if filing:
        fid = resolve_filing_id(ds, filing)
        join = (" JOIN variant_version vv ON f.variant_version_id = "
                "vv.variant_version_id JOIN submission_variant sv "
                "ON vv.variant_id = sv.variant_id")
        where.append("sv.filing_id = ?")
        params.append(fid)
    if variant:
        if filing and "#" not in variant:
            fid = resolve_filing_id(ds, filing)
            vid = resolve_variant_id(ds, f"{fid}#{variant}")
        else:
            vid = resolve_variant_id(ds, variant)
        if not join:
            join = (" JOIN variant_version vv ON f.variant_version_id = "
                    "vv.variant_version_id")
        where.append("vv.variant_id = ?")
        params.append(vid)
    if state:
        where.append("f.state_id = ?")
        params.append(state)
    if concept:
        where.append("f.concept LIKE ? ESCAPE '\\'")
        params.append(_like(concept))
    if period:
        where.append("(f.period_end = ? OR f.period_instant = ?)")
        params += [period, period]
    if lang:
        where.append("f.lang = ?")
        params.append(lang)
    if dims:
        where.append("f.canonical_dims_json LIKE ? ESCAPE '\\'")
        params.append(_like(dims))
    if unit:
        where.append("f.unit LIKE ? ESCAPE '\\'")
        params.append(_like(unit))
    if nil:
        where.append("f.isNil")
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = ds.sql(f"SELECT count(*) AS n FROM facts f{join}{w}",
                   params)[0]["n"]
    if count_only:
        return {"total": total}
    lim = "" if limit == 0 else " LIMIT ?"
    if limit != 0:
        params.append(limit)
    rows = ds.sql(f"SELECT f.* FROM facts f{join}{w} "
                  f"ORDER BY f.state_id, f.seq{lim}", params)
    dims_map = _dims_for(ds, [r["fact_id"] for r in rows])
    return {"total": total,
            "limit": limit,
            "truncated": bool(limit) and total > limit,
            "facts": [_fact_view(r, dims_map.get(r["fact_id"], []))
                      for r in rows]}


def get_fact(ds: Dataset, ref: str) -> dict:
    """One fact's complete record + provenance link."""
    fid = resolve_fact_id(ds, ref)
    row = ds.sql("SELECT * FROM facts WHERE fact_id = ?", [fid])[0]
    dims = _dims_for(ds, [fid]).get(fid, [])
    out = _fact_view(row, dims)
    prov = ds.sql("SELECT * FROM provenance WHERE state_id = ?",
                  [row["state_id"]])
    out["provenance"] = [
        {k: p[k] for k in ("state_id", "filing_id", "variant_version_id",
                           "artifact_id", "role", "sha256", "byte_size",
                           "media_type", "source_url", "resolved_url",
                           "retrieved_at", "http_status", "evidence_path",
                           "arelle_version", "lexical_shim")}
        for p in prov]
    # sibling facts sharing the structural key inside the same version —
    # multiplicity is observable, never collapsed
    dup = ds.sql(
        "SELECT count(*) AS n FROM facts WHERE variant_version_id = ? "
        "AND concept = ? AND entity_scheme IS NOT DISTINCT FROM ? "
        "AND entity IS NOT DISTINCT FROM ? "
        "AND period_start IS NOT DISTINCT FROM ? "
        "AND period_end IS NOT DISTINCT FROM ? "
        "AND period_instant IS NOT DISTINCT FROM ? "
        "AND period_forever IS NOT DISTINCT FROM ? "
        "AND unit IS NOT DISTINCT FROM ? AND lang IS NOT DISTINCT FROM ? "
        "AND canonical_dims_json IS NOT DISTINCT FROM ?",
        [row["variant_version_id"], row["concept"], row["entity_scheme"],
         row["entity"], row["period_start"], row["period_end"],
         row["period_instant"], row["period_forever"], row["unit"],
         row["lang"], row["canonical_dims_json"]])[0]["n"]
    out["structural_key_multiplicity"] = dup
    return out
