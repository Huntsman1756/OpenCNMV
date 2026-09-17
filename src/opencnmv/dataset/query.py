"""DuckDB query surface over a materialized COLUMNAR_DATASET_V1 directory.

DuckDB is a query engine over the Parquet files — never the authoritative
store. ``open_dataset`` registers one view per table and returns a
connection; ``VERIFICATION_QUERIES`` is the named query set exercised by
the G2-C verifier.
"""
from __future__ import annotations

from pathlib import Path

from opencnmv.dataset import schema as dschema


def open_dataset(dataset_dir: str | Path):
    """Open a dataset dir read-only as DuckDB views (one per table)."""
    import duckdb
    con = duckdb.connect(database=":memory:", read_only=False)
    base = Path(dataset_dir)
    for tname in dschema.TABLE_ORDER:
        p = base / f"{tname}.parquet"
        lit = str(p).replace("'", "''")
        con.execute(
            f"CREATE VIEW {tname} AS SELECT * FROM read_parquet('{lit}')")
    return con


# Named verification queries. Each returns deterministic rows
# (ORDER BY present where order matters).
VERIFICATION_QUERIES: dict[str, str] = {
    # filings by issuer / period / family
    "filings_by_issuer_family":
        "SELECT issuer_denomination, family, period_end, filing_id "
        "FROM filing ORDER BY issuer_denomination, family, period_end",
    # submitted variants per filing (IBE must show exactly one)
    "variants_per_filing":
        "SELECT filing_id, list(variant_id ORDER BY variant_id) AS variants "
        "FROM submission_variant GROUP BY filing_id ORDER BY filing_id",
    # variant-version history incl. unobserved superseded states
    "variant_version_history":
        "SELECT variant_version_id, variant_id, observed, artifact_set_id, "
        "created_by_event_id, supersedes_variant_version_id "
        "FROM variant_version ORDER BY variant_id, variant_version_id",
    # version events and their affected variants/components
    "events_with_affects":
        "SELECT e.event_id, e.event_date, e.event_type, e.scope_status, "
        "e.source_nreg, a.variant_id, a.affected_component_scope, "
        "a.component_description FROM version_event e "
        "LEFT JOIN event_affects a USING (event_id) "
        "ORDER BY e.event_id, a.affects_ordinal",
    # facts by concept
    "facts_by_concept":
        "SELECT concept, count(*) AS n FROM facts "
        "GROUP BY concept ORDER BY n DESC, concept LIMIT 25",
    # facts by native context/dimensions (typed + explicit preserved)
    "facts_by_dimensions":
        "SELECT d.dim_qname, d.dim_kind, count(*) AS n "
        "FROM fact_dimension d GROUP BY d.dim_qname, d.dim_kind "
        "ORDER BY n DESC, d.dim_qname LIMIT 25",
    # H2 CURRENT_HALF vs YTD separation (dims distinguish semantics even
    # when period_end coincides)
    "h2_current_half_vs_ytd":
        "SELECT d.member_qname, count(*) AS n FROM facts f "
        "JOIN fact_dimension d USING (fact_id) "
        "WHERE f.state_id LIKE '%-H2-%' "
        "AND d.member_qname LIKE '%ActualMiembro' "
        "GROUP BY d.member_qname ORDER BY d.member_qname",
    # typed-dimension retrieval
    "typed_dimensions":
        "SELECT fact_id, dim_qname, typed_value FROM fact_dimension "
        "WHERE dim_kind = 'T' ORDER BY fact_id, dim_qname LIMIT 50",
    # BBVA divergent submission fact: same structural key across variants,
    # different payload (the +98M/-98M Equity divergence is among them)
    "bbva_divergent_equity":
        "SELECT es.concept, es.value_full AS es_value, "
        "en.value_full AS en_value, es.decimals, es.lang, en.lang "
        "FROM facts es JOIN facts en "
        "ON es.concept = en.concept "
        "AND es.entity_scheme IS NOT DISTINCT FROM en.entity_scheme "
        "AND es.entity IS NOT DISTINCT FROM en.entity "
        "AND es.period_start IS NOT DISTINCT FROM en.period_start "
        "AND es.period_end IS NOT DISTINCT FROM en.period_end "
        "AND es.period_instant IS NOT DISTINCT FROM en.period_instant "
        "AND es.unit IS NOT DISTINCT FROM en.unit "
        "AND es.canonical_dims_json IS NOT DISTINCT FROM "
        "en.canonical_dims_json "
        "WHERE es.state_id = 'BBVA-FY2024-es' "
        "AND en.state_id = 'BBVA-FY2024-en' "
        "AND es.value_sha256 <> en.value_sha256 "
        "ORDER BY es.concept",
    # extension mappings by verdict
    "mappings_by_verdict":
        "SELECT verdict, count(*) AS n FROM extension_mapping "
        "GROUP BY verdict ORDER BY verdict",
    # provenance: fact -> variant_version -> artifact -> preserved source
    "fact_provenance":
        "SELECT f.fact_id, f.variant_version_id, p.artifact_id, p.sha256, "
        "p.evidence_path FROM facts f JOIN provenance p "
        "ON f.variant_version_id = p.variant_version_id "
        "ORDER BY f.fact_id LIMIT 25",
    # referential integrity spot: facts with no variant_version row
    "orphan_facts":
        "SELECT count(*) AS n FROM facts f LEFT JOIN variant_version v "
        "ON f.variant_version_id = v.variant_version_id "
        "WHERE v.variant_version_id IS NULL",
}
