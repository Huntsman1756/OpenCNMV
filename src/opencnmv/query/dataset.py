"""Dataset resolution, open and integrity gating for the read surface.

Resolution contract (first hit wins):

    1. explicit --dataset PATH
    2. OPENCNMV_DATASET environment variable
    3. ./dataset/v1 (cwd default — only when it exists)

Opening a dataset always verifies the manifest (per-file sha256, row
counts, on-disk Arrow schemas vs the pinned COLUMNAR_DATASET_V1 schemas)
before any data is served — a corrupted dataset fails closed, it is never
presented as trustworthy. ``validate_dataset`` additionally recomputes
every table's logical sha256, the corpus logical hash, referential
integrity and update invariants.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from opencnmv.dataset import manifest as dmanifest
from opencnmv.dataset import schema as dschema
from opencnmv.query.errors import (
    AmbiguousIdentifierError, DatasetIntegrityError, DatasetNotFoundError,
    MissingDependencyError, NotFoundError)

DATASET_ENV_VAR = "OPENCNMV_DATASET"
DEFAULT_DATASET_DIR = Path("dataset") / "v1"
MANIFEST_NAME = "dataset_manifest.json"


def _duckdb():
    try:
        import duckdb
        return duckdb
    except ImportError as e:
        raise MissingDependencyError(
            "duckdb is required for dataset queries; install the "
            "'dataset' extra (pip install opencnmv[dataset])") from e


def _pyarrow_parquet():
    try:
        from pyarrow import parquet as pq
        return pq
    except ImportError as e:
        raise MissingDependencyError(
            "pyarrow is required for dataset queries; install the "
            "'dataset' extra (pip install opencnmv[dataset])") from e


def resolve_dataset_path(explicit: str | None = None,
                         env: dict | None = None) -> Path:
    """Apply the documented precedence; does not check existence."""
    if explicit:
        return Path(explicit)
    environ: dict = os.environ if env is None else env  # type: ignore[assignment]
    if environ.get(DATASET_ENV_VAR):
        return Path(environ[DATASET_ENV_VAR])
    return DEFAULT_DATASET_DIR


class Dataset:
    """An opened, manifest-verified COLUMNAR_DATASET_V1 directory.

    ``con`` is a DuckDB in-memory connection with one read view per
    table — a query surface only, never the authoritative store. The CLI
    never opens dataset files for writing.
    """

    def __init__(self, path: Path, manifest: dict, con):
        self.path = path
        self.manifest = manifest
        self.con = con

    def sql(self, q: str, params: list | None = None) -> list[dict]:
        cur = self.con.execute(q, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _open_views(base: Path):
    """In-memory DuckDB connection with one Parquet view per table."""
    duckdb = _duckdb()
    con = duckdb.connect(database=":memory:", read_only=False)
    for tname in dschema.TABLE_ORDER:
        p = base / f"{tname}.parquet"
        lit = str(p).replace("'", "''")
        con.execute(
            f"CREATE VIEW {tname} AS SELECT * FROM read_parquet('{lit}')")
    return con


def open_dataset(path: str | Path, *, verify: bool = True) -> Dataset:
    """Resolve, verify and open a dataset directory.

    verify=True runs the manifest gate (file sha256 + row count + Arrow
    schema equality) before serving — the read-path fail-closed check.
    """
    base = Path(path)
    mpath = base / MANIFEST_NAME
    if not base.is_dir() or not mpath.is_file():
        raise DatasetNotFoundError(
            f"not a COLUMNAR_DATASET_V1 directory: {base} "
            f"(missing {'directory' if not base.is_dir() else MANIFEST_NAME})")
    try:
        man = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise DatasetNotFoundError(
            f"unreadable {MANIFEST_NAME} in {base}: {e}") from e
    if man.get("dataset") != "COLUMNAR_DATASET":
        raise DatasetNotFoundError(
            f"{mpath}: not a COLUMNAR_DATASET manifest")
    if verify:
        try:
            violations = dmanifest.verify_manifest(base, man)
        except ImportError as e:
            raise MissingDependencyError(
                "pyarrow is required to verify the dataset manifest; "
                "install the 'dataset' extra "
                "(pip install opencnmv[dataset])") from e
        if violations:
            raise DatasetIntegrityError(
                "dataset fails manifest verification: "
                + "; ".join(violations[:8]))
    try:
        con = _open_views(base)
    except MissingDependencyError:
        raise
    except Exception as e:
        raise DatasetNotFoundError(
            f"cannot open dataset at {base}: {e}") from e
    return Dataset(base, man, con)


def table_rows(ds: Dataset, table: str) -> list[dict]:
    """Small-model-table row list in canonical ROW_ORDER."""
    from opencnmv.dataset import parquetio
    rows = ds.sql(f"SELECT * FROM {table}")
    return sorted(rows, key=parquetio.ROW_ORDER[table])


def dataset_info(ds: Dataset) -> dict:
    """Everything `dataset info` exposes, as a plain dict."""
    man = ds.manifest
    tables = man["tables"]
    counts = {
        "filings": tables["filing"]["rows"],
        "filing_versions": tables["filing_version"]["rows"],
        "submission_variants": tables["submission_variant"]["rows"],
        "variant_versions": tables["variant_version"]["rows"],
        "view_resolutions": tables["view_resolution"]["rows"],
        "version_events": tables["version_event"]["rows"],
        "event_affects": tables["event_affects"]["rows"],
        "artifacts": tables["artifact"]["rows"],
        "extension_mappings": tables["extension_mapping"]["rows"],
        "provenance_states": tables["provenance"]["rows"],
        "facts": tables["facts"]["rows"],
        "fact_dimensions": tables["fact_dimension"]["rows"],
    }
    return {
        "dataset": "COLUMNAR_DATASET",
        "dataset_version": man["dataset_version"],
        "canonical_model": man["canonical_model"],
        "corpus_logical_sha256": man["corpus_logical_sha256"],
        "schema_fingerprint": man["schema_fingerprint"],
        "code_commit": man.get("code_commit"),
        "generator": man.get("generator"),
        "build_parameters": man.get("build_parameters"),
        "tables": {t: {"rows": m["rows"], "sha256": m["sha256"],
                       "logical_sha256": m["logical_sha256"]}
                   for t, m in tables.items()},
        "counts": counts,
        "inputs": man.get("inputs", {}),
        "findings": man.get("findings", []),
        "limitations": man.get("limitations", []),
        "integrity": {"manifest_verified": True},
    }


def validate_dataset(ds: Dataset) -> dict:
    """Deep validation: manifest + required files + schemas + referential
    + update invariants + per-table and corpus logical hash recomputation.

    Returns {"checks": [{name, status, detail}], "status": PASS|FAIL}.
    """
    from opencnmv.dataset import integrity as dint
    from opencnmv.dataset import parquetio
    from opencnmv.update import integrity as uint

    pq = _pyarrow_parquet()
    checks: list[dict] = []

    def ck(name, ok, detail=""):
        checks.append({"name": name,
                       "status": "PASS" if ok else "FAIL",
                       "detail": detail})

    base = ds.path
    man = ds.manifest

    # required files
    missing = [t for t in dschema.TABLE_ORDER
               if not (base / f"{t}.parquet").is_file()]
    missing += [f"schema/{t}.schema.json" for t in dschema.TABLE_ORDER
                if not (base / "schema" / f"{t}.schema.json").is_file()]
    ck("required_files", not missing, f"missing={missing}")

    # manifest: file sha256 + row count + on-disk schema
    v = dmanifest.verify_manifest(base, man)
    ck("manifest_hashes_rows_schemas", not v, "; ".join(v[:8]))

    # exported schema docs match pinned fingerprints
    bad_schema = []
    from opencnmv.provenance.hashes import sha256_file
    for t in dschema.TABLE_ORDER:
        p = base / "schema" / f"{t}.schema.json"
        if p.is_file() and \
                sha256_file(p) != dschema.schema_fingerprint(t):
            bad_schema.append(t)
    ck("exported_schema_fingerprints", not bad_schema,
       f"mismatched={bad_schema}")

    # load tables, logical hash per table + corpus hash
    tables: dict[str, list[dict]] = {}
    load_err = []
    logical_bad = []
    table_hashes: dict[str, str] = {}
    for t in dschema.TABLE_ORDER:
        p = base / f"{t}.parquet"
        if not p.is_file():
            continue
        try:
            rows = pq.read_table(p).to_pylist()
        except Exception as e:  # noqa: BLE001
            load_err.append(f"{t}: {e}")
            continue
        tables[t] = rows
        lh = parquetio.logical_hash(t, sorted(
            rows, key=parquetio.ROW_ORDER[t]))
        table_hashes[t] = lh
        if lh != man["tables"][t]["logical_sha256"]:
            logical_bad.append(t)
    ck("tables_readable", not load_err, "; ".join(load_err[:4]))
    ck("logical_hashes_match_manifest", not logical_bad,
       f"mismatched={logical_bad}")
    if not logical_bad and len(table_hashes) == len(dschema.TABLE_ORDER):
        corpus = dmanifest.corpus_hash(table_hashes)
        ck("corpus_logical_hash",
           corpus == man["corpus_logical_sha256"], corpus)

    # referential + update invariants
    if len(tables) == len(dschema.TABLE_ORDER):
        errs = dint.check(tables) + uint.check_update_invariants(tables)
        ck("referential_and_update_invariants", not errs,
           "; ".join(errs[:8]))

    status = "PASS" if all(c["status"] == "PASS" for c in checks) \
        else "FAIL"
    return {"status": status, "dataset_version": man["dataset_version"],
            "canonical_model": man["canonical_model"],
            "corpus_logical_sha256": man["corpus_logical_sha256"],
            "checks": checks}


# --- identifier resolution ----------------------------------------------------

def resolve_filing_id(ds: Dataset, ref: str) -> str:
    """REF = canonical filing_id | exact registro_oficial. Exit-4 /
    exit-2 semantics via exceptions."""
    hit = ds.sql("SELECT filing_id FROM filing WHERE filing_id = ?",
                 [ref])
    if hit:
        return hit[0]["filing_id"]
    hits = ds.sql("SELECT filing_id FROM filing WHERE registro_oficial = ?",
                  [ref])
    if len(hits) == 1:
        return hits[0]["filing_id"]
    if len(hits) > 1:
        raise AmbiguousIdentifierError(
            f"{ref!r} matches {len(hits)} filings; use the canonical "
            f"filing_id")
    raise NotFoundError(f"no filing with id or registro_oficial {ref!r}")


def resolve_variant_id(ds: Dataset, ref: str) -> str:
    """REF = canonical variant_id. Bare '<filing>#<lang>' shorthand is the
    canonical form already — no other aliasing."""
    hit = ds.sql(
        "SELECT variant_id FROM submission_variant WHERE variant_id = ?",
        [ref])
    if hit:
        return hit[0]["variant_id"]
    raise NotFoundError(f"no submission_variant {ref!r}")


def resolve_fact_id(ds: Dataset, ref: str) -> str:
    """Accepts the canonical fact_id ('fact:<sha>'/'fact:<sha>#<occ>') or
    the bare hash with/without occurrence suffix."""
    candidates = [ref] if ref.startswith("fact:") else \
        [ref, f"fact:{ref}"]
    for c in candidates:
        hit = ds.sql("SELECT fact_id FROM facts WHERE fact_id = ?", [c])
        if hit:
            return hit[0]["fact_id"]
    raise NotFoundError(f"no fact {ref!r}")
