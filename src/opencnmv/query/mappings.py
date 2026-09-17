"""Extension-mapping query surface.

Every mapping verdict is exposed verbatim. `rewrites_identity` is true
exactly when verdict == PROVEN_EQUIVALENT; no flag or caller can promote
AMBIGUOUS / CONFLICT / UNMATCHED rows into identity merges.
"""
from __future__ import annotations

from opencnmv.query.dataset import Dataset, resolve_filing_id

REWRITING_VERDICT = "PROVEN_EQUIVALENT"


def filing_mappings(ds: Dataset, ref: str,
                    verdict: str | None = None) -> dict:
    fid = resolve_filing_id(ds, ref)
    where = "WHERE filing_id = ?"
    params: list = [fid]
    if verdict:
        where += " AND verdict = ?"
        params.append(verdict)
    rows = ds.sql(
        f"SELECT * FROM extension_mapping {where} "
        "ORDER BY source_qname, target_qname", params)
    out = []
    for m in rows:
        m = dict(m)
        m["rewrites_identity"] = (m["verdict"] == REWRITING_VERDICT)
        out.append(m)
    by_verdict: dict[str, int] = {}
    for m in out:
        by_verdict[m["verdict"]] = by_verdict.get(m["verdict"], 0) + 1
    return {"filing_id": fid,
            "rule": "only PROVEN_EQUIVALENT may rewrite cross-variant "
                    "identity; all other verdicts stay unresolved",
            "counts_by_verdict": by_verdict,
            "mappings": out}
