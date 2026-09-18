"""Dataset bootstrap: empty destination -> COLUMNAR_DATASET_V1.

``init`` is the delta engine applied to an empty base: the observation
is planned against zero rows (an all-rows delta), merged, checked
against the full integrity gate, staged into a sibling directory and
published by a single rename. There is no prior manifest to bind to —
the base is the fixed empty corpus.

Publish discipline (mirrors ``apply_delta``):

  * the destination never holds a partially-valid dataset — it is
    either absent/empty or the complete staged result;
  * a crash before the final rename leaves only the ``.staging-init``
    sibling, which is never authoritative and is cleaned on the next
    run;
  * V1 offers no overwrite: a non-empty destination is refused before
    any work happens.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from opencnmv.dataset import integrity as dint
from opencnmv.dataset import manifest as dmanifest
from opencnmv.dataset import parquetio
from opencnmv.dataset import schema as dschema
from opencnmv.query.errors import UsageError
from opencnmv.serialize import write_canonical
from opencnmv.update import delta as delta_mod
from opencnmv.update import integrity as uint
from opencnmv.update.apply import DeltaError

# corpus_logical_sha256 of the empty corpus — the fixed bootstrap base.
EMPTY_CORPUS_SHA256 = "0" * 64


def init_dataset(dataset_dir: str | Path, observation: dict, *,
                 code_commit: str = "",
                 generator: dict | None = None,
                 fail_hook: str | None = None) -> dict:
    """Bootstrap a dataset from a verified observation document.

    ``dataset_dir`` must be absent or an empty directory; a non-empty
    destination raises ``UsageError`` (no overwrite in V1). Returns a
    result dict {"status": "INITIALIZED", ...}. Raises ``DeltaError``
    when the observation or the merged state fails verification.
    """
    dest = Path(dataset_dir)
    if dest.exists():
        if not dest.is_dir():
            raise UsageError(
                f"init destination is not a directory: {dest}")
        if any(dest.iterdir()):
            raise UsageError(
                f"init destination is not empty: {dest} — "
                "no overwrite in V1; choose an empty directory")

    empty: dict[str, list[dict]] = {
        t: [] for t in dschema.TABLE_ORDER}
    delta = delta_mod.plan(empty, observation, EMPTY_CORPUS_SHA256)
    errs = delta_mod.verify_delta(delta)
    if errs:
        raise DeltaError("bootstrap delta failed verification: "
                         + "; ".join(errs))
    merged = delta_mod.merged_tables(empty, {
        "added": delta["rows_added"],
        "updated": delta["rows_updated"],
        "removed": delta["rows_removed"]})
    errs = dint.check(merged) + uint.check_update_invariants(merged)
    if errs:
        raise DeltaError("bootstrapped state violates integrity: "
                         + "; ".join(errs[:8]))

    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.parent / f"{dest.name}.staging-init"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        if fail_hook == "before_tables":
            raise RuntimeError("injected failure: before_tables")
        table_meta = {}
        for tname in dschema.TABLE_ORDER:
            table_meta[tname] = parquetio.write_table(
                tname, merged[tname], staging / f"{tname}.parquet")
            if fail_hook == f"during_table:{tname}":
                raise RuntimeError(f"injected failure: {tname}")
        schema_dir = staging / "schema"
        schema_dir.mkdir(exist_ok=True)
        for tname in dschema.TABLE_ORDER:
            write_canonical(dschema.schema_dict(tname),
                            schema_dir / f"{tname}.schema.json")
        man = dmanifest.build_manifest(
            inputs={
                "base_dataset": {"corpus_logical_sha256":
                                 EMPTY_CORPUS_SHA256},
                "observation": {
                    "observation_id": delta["observation_id"],
                    "observation_sha256":
                        delta["observation_sha256"]},
                "delta": {"delta_id": delta["delta_id"],
                          "delta_format": delta_mod.DELTA_FORMAT},
                "bootstrap": {"engine": "opencnmv.update.bootstrap",
                              "mode": "empty-base all-rows delta"}},
            tables=table_meta, code_commit=code_commit,
            generator=generator or {"tool": "opencnmv init"},
            params={"compression": "zstd",
                    "row_order": "canonical sorted",
                    "update_mode": "bootstrap (empty base -> "
                                   "all-rows delta)"},
            findings=[f"bootstrapped {delta['observation_id']} "
                      f"({len(delta['transitions'])} filings)"])
        write_canonical(man, staging / "dataset_manifest.json")
        bad = dmanifest.verify_manifest(staging, man)
        if bad:
            raise DeltaError("staged dataset fails manifest: "
                             + "; ".join(bad))
        if man["corpus_logical_sha256"] != \
                delta["result_corpus_logical_sha256"]:
            raise DeltaError("staged corpus hash != delta prediction")
        if fail_hook == "before_publish":
            raise RuntimeError("injected failure: before_publish")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # publish: dest is absent or an empty directory — a single rename
    # makes the staged result authoritative.
    if dest.exists():
        shutil.rmtree(dest)
    os.rename(staging, dest)
    return {"status": "INITIALIZED",
            "corpus_logical_sha256": man["corpus_logical_sha256"],
            "delta_id": delta["delta_id"],
            "transitions": len(delta["transitions"])}
