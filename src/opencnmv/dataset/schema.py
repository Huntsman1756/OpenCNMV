"""Arrow schemas for the columnar dataset (COLUMNAR_DATASET_V1).

Design contract:
  * model/relational layer (filing, filing_version, submission_variant,
    variant_version, view_resolution, version_event, event_affects,
    extension_mapping, artifact, provenance) is stored separately from
    the fact plane (facts + fact_dimension).
  * every table has an explicit, deterministic schema; ordinals preserve
    canonical object order so reconstruction is byte-exact.
  * the fact plane keeps structural identity columns separate from
    payload columns, plus a lossless canonical_dims_json encoding of the
    full dimension multiset (explicit + typed) so native context
    equality is never guessed from a text blob.
  * raw evidence records that do not fit the frozen Canonical Model V1
    shape (e.g. G1-C UNMATCHED mapping records) are preserved losslessly
    in record_json columns.
"""
from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = "COLUMNAR_DATASET_V1"
CANONICAL_MODEL_VERSION = "CANONICAL_MODEL_V1"

FILING = pa.schema([
    ("filing_id", pa.string()),
    ("issuer_denomination", pa.string()),
    ("issuer_nif", pa.string()),
    ("issuer_lei", pa.string()),
    ("registro_oficial", pa.string()),
    ("family", pa.string()),
    ("period_end", pa.string()),
    ("extras_json", pa.string()),          # non-schema fixture extras, canonical JSON
])

FILING_VERSION = pa.schema([
    ("filing_version_id", pa.string()),
    ("filing_id", pa.string()),
    ("source_nreg", pa.string()),
    ("filed_at", pa.string()),
    ("submission_kind", pa.string()),
    ("version_seq", pa.int64()),
])

SUBMISSION_VARIANT = pa.schema([
    ("variant_id", pa.string()),
    ("filing_id", pa.string()),
    ("submission_language", pa.string()),
    ("variant_ordinal", pa.int64()),
])

VARIANT_VERSION = pa.schema([
    ("variant_version_id", pa.string()),
    ("variant_id", pa.string()),
    ("version_seq", pa.int64()),
    ("observed", pa.bool_()),
    ("artifact_set_id", pa.string()),
    ("created_by_event_id", pa.string()),
    ("supersedes_variant_version_id", pa.string()),
])

VIEW_RESOLUTION = pa.schema([
    ("filing_id", pa.string()),
    ("requested_ui_language", pa.string()),
    ("resolved_variant_id", pa.string()),
    ("resolution_mode", pa.string()),
    ("ordinal", pa.int64()),
])

VERSION_EVENT = pa.schema([
    ("event_id", pa.string()),
    ("filing_id", pa.string()),
    ("event_date", pa.string()),
    ("event_type", pa.string()),
    ("source_label", pa.string()),
    ("source_nreg", pa.string()),          # nullable by contract (V1)
    ("evidence_artifact_id", pa.string()),
    ("scope_status", pa.string()),
])

EVENT_AFFECTS = pa.schema([
    ("event_id", pa.string()),
    ("affects_ordinal", pa.int64()),
    ("variant_id", pa.string()),           # nullable: scoped unknown
    ("affected_component_scope", pa.string()),
    ("component_description", pa.string()),
    ("before_variant_version_id", pa.string()),
    ("after_variant_version_id", pa.string()),
    ("scope_basis", pa.string()),
])

ARTIFACT = pa.schema([
    ("owner_kind", pa.string()),           # variant_version | filing_version | version_event
    ("owner_id", pa.string()),
    ("artifact_ordinal", pa.int64()),
    ("artifact_id", pa.string()),
    ("role", pa.string()),
    ("sha256", pa.string()),
    ("bytes", pa.int64()),
    ("media_type", pa.string()),
    ("source_url", pa.string()),
    ("package_lang_tag", pa.string()),
])

EXTENSION_MAPPING = pa.schema([
    ("filing_id", pa.string()),
    ("source_file", pa.string()),
    ("source_ordinal", pa.int64()),
    ("pair_id", pa.string()),              # null for unpaired records
    ("source_variant_id", pa.string()),
    ("target_variant_id", pa.string()),
    ("source_qname", pa.string()),
    ("target_qname", pa.string()),
    ("mapping_type", pa.string()),
    ("verdict", pa.string()),
    ("rewrites_identity", pa.bool_()),
    ("record_json", pa.string()),          # lossless raw G1-C record
])

PROVENANCE = pa.schema([
    ("state_id", pa.string()),
    ("filing_id", pa.string()),
    ("variant_version_id", pa.string()),
    ("artifact_id", pa.string()),
    ("role", pa.string()),
    ("sha256", pa.string()),
    ("byte_size", pa.int64()),
    ("media_type", pa.string()),
    ("source_url", pa.string()),
    ("resolved_url", pa.string()),
    ("retrieved_at", pa.string()),
    ("http_status", pa.int64()),
    ("evidence_path", pa.string()),
    ("arelle_version", pa.string()),
    ("lexical_shim", pa.bool_()),
])

# facts.parquet columns mirror the frozen facts.jsonl record keys 1:1 so a
# row -> record reconstruction is byte-exact under json.dumps(sort_keys=True).
# Metadata/derived columns (fact_id, state_id, variant_version_id, seq,
# profile, unit_*_count, *_dim_count, canonical_dims_json) are dataset-only.
FACTS = pa.schema([
    ("fact_id", pa.string()),              # structural key + variant_version identity hash
    ("state_id", pa.string()),             # frozen corpus state (e.g. SAN-H1-2024)
    ("variant_version_id", pa.string()),
    ("seq", pa.int64()),                   # deterministic order within state
    ("profile", pa.string()),              # esef | ipp (record key set)
    # --- canonical record: structural identity (native XBRL context) ---
    ("concept", pa.string()),              # native QName "ns#local"
    ("entity_scheme", pa.string()),
    ("entity", pa.string()),
    ("period_start", pa.string()),
    ("period_end", pa.string()),
    ("period_instant", pa.string()),
    ("period_forever", pa.bool_()),
    ("contextID", pa.string()),
    ("unit", pa.string()),                 # complete sig: num*num/den*den
    ("unitID", pa.string()),
    ("lang", pa.string()),                 # xml:lang
    # --- canonical record: payload (separate from identity) ---
    ("value_sha256", pa.string()),
    ("value_len", pa.int64()),
    ("value_preview", pa.string()),
    ("xValue_sha256", pa.string()),
    ("xValue_len", pa.int64()),
    ("xValue_preview", pa.string()),
    ("isNil", pa.bool_()),
    ("decimals", pa.string()),
    # --- esef-profile extra record fields ---
    ("concept_type", pa.string()),
    ("is_numeric", pa.bool_()),
    ("value_full", pa.string()),
    ("xValue_full", pa.string()),
    ("ns_kind", pa.string()),
    # --- derived query columns (deterministic) ---
    ("unit_numerator", pa.string()),       # ordered measures, *-separated
    ("unit_denominator", pa.string()),
    ("unit_numerator_count", pa.int64()),
    ("unit_denominator_count", pa.int64()),
    ("explicit_dim_count", pa.int64()),
    ("typed_dim_count", pa.int64()),
    ("canonical_dims_json", pa.string()),  # lossless canonical JSON of dims
])

FACT_DIMENSION = pa.schema([
    ("fact_id", pa.string()),
    ("dim_qname", pa.string()),
    ("dim_kind", pa.string()),             # E | T  (explicit | typed)
    ("member_qname", pa.string()),
    ("typed_value", pa.string()),
])

TABLE_ORDER = [
    "filing", "filing_version", "submission_variant", "variant_version",
    "view_resolution", "version_event", "event_affects", "artifact",
    "extension_mapping", "provenance",
    "facts", "fact_dimension",
]

SCHEMAS = {
    "filing": FILING,
    "filing_version": FILING_VERSION,
    "submission_variant": SUBMISSION_VARIANT,
    "variant_version": VARIANT_VERSION,
    "view_resolution": VIEW_RESOLUTION,
    "version_event": VERSION_EVENT,
    "event_affects": EVENT_AFFECTS,
    "artifact": ARTIFACT,
    "extension_mapping": EXTENSION_MAPPING,
    "provenance": PROVENANCE,
    "facts": FACTS,
    "fact_dimension": FACT_DIMENSION,
}

MODEL_TABLES = [t for t in TABLE_ORDER if t not in ("facts",
                                                   "fact_dimension")]
FACT_TABLES = ["facts", "fact_dimension"]


def schema_dict(name: str) -> dict:
    """Deterministic JSON-able description of one table's Arrow schema."""
    sch = SCHEMAS[name]
    return {"table": name,
            "fields": [{"name": f.name,
                        "type": str(f.type),
                        "nullable": f.nullable}
                       for f in sch]}


def schema_fingerprint(name: str) -> str:
    import hashlib
    import json
    body = json.dumps(schema_dict(name), indent=1,
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()
