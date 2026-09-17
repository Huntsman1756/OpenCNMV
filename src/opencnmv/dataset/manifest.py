"""dataset_manifest.json — reproducibility contract for a materialized
dataset directory.

Records dataset/canonical-model versions, generator identity, pinned
inputs, per-table row counts + file SHA-256 + logical row-hash + schema
fingerprint, and build parameters that affect output. No absolute paths.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from opencnmv.dataset import schema as dschema
from opencnmv.provenance.hashes import canon, sha256_bytes


def schema_fingerprint() -> str:
    """sha256 over all per-table schema fingerprints (stable order)."""
    return hashlib.sha256(canon(
        {t: dschema.schema_fingerprint(t)
         for t in dschema.TABLE_ORDER}).encode("utf-8")).hexdigest()


def corpus_hash(table_hashes: dict[str, str]) -> str:
    """Deterministic logical corpus hash over per-table logical hashes."""
    return hashlib.sha256(canon(
        {t: table_hashes[t] for t in sorted(table_hashes)}).encode("utf-8")
    ).hexdigest()


def build_manifest(*, inputs: dict, tables: dict[str, dict],
                   code_commit: str, generator: dict, params: dict,
                   findings: list[str] | None = None,
                   limitations: list[str] | None = None) -> dict:
    return {
        "dataset": "COLUMNAR_DATASET",
        "dataset_version": dschema.SCHEMA_VERSION,
        "canonical_model": dschema.CANONICAL_MODEL_VERSION,
        "code_commit": code_commit,
        "generator": generator,
        "build_parameters": params,
        "schema_fingerprint": schema_fingerprint(),
        "inputs": inputs,
        "tables": tables,
        "corpus_logical_sha256": corpus_hash(
            {t: m["logical_sha256"] for t, m in tables.items()}),
        "findings": findings or [],
        "limitations": limitations or []}


def verify_manifest(dataset_dir: str | Path, manifest: dict) -> list[str]:
    """Re-hash every table file; return a list of violations (empty=OK)."""
    from pyarrow import parquet as pq
    errors = []
    for tname, meta in manifest["tables"].items():
        p = Path(dataset_dir) / meta["file"]
        if not p.is_file():
            errors.append(f"{tname}: missing {meta['file']}")
            continue
        got = sha256_bytes(p.read_bytes())
        if got != meta["sha256"]:
            errors.append(f"{tname}: sha256 mismatch")
            continue
        n_rows = pq.read_metadata(p).num_rows
        if n_rows != meta["rows"]:
            errors.append(f"{tname}: row count {n_rows} != {meta['rows']}")
        if not pq.read_schema(p).equals(dschema.SCHEMAS[tname]):
            errors.append(f"{tname}: on-disk schema != pinned schema")
    return errors
