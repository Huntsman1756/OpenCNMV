"""Deterministic Parquet read/write + logical table hashing.

Write path fixes schema, row order (caller-sorted), compression and
metadata so two runs over identical rows produce byte-identical files on
the same pyarrow build. The logical hash is independent of Parquet
encoding: sha256 over the canonical JSON of every row in table order.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from opencnmv.dataset import schema as dschema
from opencnmv.provenance.hashes import canon, sha256_bytes

# Deterministic row order per table — the dataset write contract. The
# materializer and the update engine must use exactly this ordering so
# identical row sets serialize to byte-identical Parquet.
ROW_ORDER = {
    "filing": lambda r: r["filing_id"],
    "filing_version": lambda r: (r["filing_id"], r["version_seq"]),
    "submission_variant": lambda r: (r["filing_id"],
                                     r["variant_ordinal"]),
    "variant_version": lambda r: r["variant_version_id"],
    "view_resolution": lambda r: (r["filing_id"], r["ordinal"]),
    "version_event": lambda r: r["event_id"],
    "event_affects": lambda r: (r["event_id"], r["affects_ordinal"]),
    "artifact": lambda r: (r["owner_kind"], r["owner_id"],
                           r["artifact_ordinal"]),
    "extension_mapping": lambda r: (r["filing_id"], r["source_file"],
                                    r["source_ordinal"]),
    "provenance": lambda r: r["state_id"],
    "facts": lambda r: (r["state_id"], r["seq"]),
    "fact_dimension": lambda r: (r["fact_id"], r["dim_qname"]),
}


def logical_hash(table_name: str, rows: list[dict]) -> str:
    """sha256 over canonical JSON lines of the row projection."""
    cols = [f.name for f in dschema.SCHEMAS[table_name]]
    h = hashlib.sha256()
    for r in rows:
        h.update(canon({c: r.get(c) for c in cols}).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def write_table(table_name: str, rows: list[dict], path: str | Path) -> dict:
    """Write a deterministic Parquet file; return hash metadata."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    sch = dschema.SCHEMAS[table_name]
    arrays = [pa.array([r.get(f.name) for r in rows], type=f.type)
              for f in sch]
    table = pa.Table.from_arrays(arrays, schema=sch)
    pq.write_table(table, path, compression="zstd",
                   write_statistics=False)
    return {"file": Path(path).name, "rows": len(rows),
            "sha256": sha256_bytes(Path(path).read_bytes()),
            "logical_sha256": logical_hash(table_name, rows),
            "schema_fingerprint": dschema.schema_fingerprint(table_name)}


def read_table(path: str | Path) -> list[dict]:
    import pyarrow.parquet as pq
    return pq.read_table(path).to_pylist()


def table_schema_ok(table_name: str, path: str | Path) -> bool:
    """The on-disk Arrow schema must equal the pinned table schema."""
    import pyarrow.parquet as pq
    return pq.read_schema(path).equals(dschema.SCHEMAS[table_name])
