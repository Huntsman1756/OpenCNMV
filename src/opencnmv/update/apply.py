"""Delta application with stale-base control and staged publish.

Authoritative storage is Parquet + manifest (never DuckDB). Apply flow:

  1. load the dataset manifest; require
     ``manifest.corpus_logical_sha256 == delta.base_corpus_logical_sha256``
     — a delta is bound to the exact base it was planned against.
  2. verify the delta document (format + self-hash + row shapes).
  3. merge rows purely in memory; run full referential integrity plus
     update invariants BEFORE anything is written.
  4. write the complete S1 into a sibling staging directory
     (``<name>.staging-<delta_id[:12]>``), including schema JSON and a new
     manifest whose inputs record base hash + delta id + observation hash.
  5. verify the staged manifest and the predicted result hash.
  6. publish by directory rename: ``v1 -> v1.prev-<n>``,
     ``staging -> v1``, remove prev. A crash before the final rename
     leaves the original dataset untouched; a crash mid-swap leaves
     ``.prev-`` available for rollback and the staging dir is never
     authoritative.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from opencnmv.dataset import integrity as dint
from opencnmv.dataset import manifest as dmanifest
from opencnmv.dataset import parquetio
from opencnmv.dataset import schema as dschema
from opencnmv.serialize import write_canonical
from opencnmv.update import classify as classify_mod
from opencnmv.update import delta as delta_mod
from opencnmv.update import integrity as uint


class StaleBaseError(RuntimeError):
    """Delta was planned against a different base dataset."""


class DeltaError(ValueError):
    """Delta failed structural/semantic verification."""


def load_manifest(dataset_dir: Path) -> dict:
    return json.loads((Path(dataset_dir) / "dataset_manifest.json")
                      .read_text(encoding="utf-8"))


def load_tables(dataset_dir: Path) -> dict[str, list[dict]]:
    ds = Path(dataset_dir)
    return {t: parquetio.read_table(ds / f"{t}.parquet")
            for t in dschema.TABLE_ORDER}


def _merge_checked(base: dict[str, list[dict]],
                   delta: dict) -> dict[str, list[dict]]:
    merged = {t: list(base.get(t, [])) for t in dschema.TABLE_ORDER}
    for t, rows in delta["rows_removed"].items():
        pk = classify_mod.PK[t]
        drop = {pk(r): r for r in rows}
        for r in merged[t]:
            k = pk(r)
            if k in drop:
                if drop[k] != r:
                    raise DeltaError(f"{t}: rows_removed content mismatch "
                                     f"for {k}")
        merged[t] = [r for r in merged[t] if pk(r) not in drop]
    for t, ups in delta["rows_updated"].items():
        pk = classify_mod.PK[t]
        amap = {tuple(u["pk"]): u for u in ups}
        out = []
        for r in merged[t]:
            u = amap.get(pk(r))
            if u is None:
                out.append(r)
                continue
            if u["before"] != r:
                raise DeltaError(f"{t}: rows_updated before-image mismatch "
                                 f"for {pk(r)}")
            out.append(u["after"])
        merged[t] = out
        if len(amap) != len(ups):
            raise DeltaError(f"{t}: duplicate pk in rows_updated")
        seen = {tuple(u["pk"]) for u in ups}
        present = {pk(r) for r in merged[t]}
        missing = seen - present
        if missing:
            raise DeltaError(f"{t}: rows_updated target missing {missing}")
    for t, rows in delta["rows_added"].items():
        pk = classify_mod.PK[t]
        existing = {pk(r) for r in merged[t]}
        for r in rows:
            if pk(r) in existing:
                raise DeltaError(f"{t}: rows_added duplicates existing "
                                 f"identity {pk(r)}")
            merged[t].append(r)
            existing.add(pk(r))
    return {t: sorted(merged[t], key=parquetio.ROW_ORDER[t])
            for t in dschema.TABLE_ORDER}


def apply_delta(dataset_dir: str | Path, delta: dict, *,
                code_commit: str = "", generator: dict | None = None,
                fail_hook: str | None = None) -> dict:
    """Apply a verified delta to a materialized dataset directory.

    Returns a result dict: {"status": "NO_CHANGE"|"APPLIED",
    "corpus_logical_sha256", "staging_dir", ...}
    Raises StaleBaseError / DeltaError on refusal — the dataset directory
    is never left half-updated.
    """
    ds = Path(dataset_dir)
    man = load_manifest(ds)
    base_hash = man["corpus_logical_sha256"]
    if delta.get("base_corpus_logical_sha256") != base_hash:
        raise StaleBaseError(
            f"delta base {delta.get('base_corpus_logical_sha256')} != "
            f"dataset {base_hash}")
    errs = delta_mod.verify_delta(delta)
    if errs:
        raise DeltaError("; ".join(errs))

    base = load_tables(ds)
    merged = _merge_checked(base, delta)
    no_ops = (not any(delta["rows_added"].values())
              and not any(delta["rows_updated"].values())
              and not any(delta["rows_removed"].values()))
    if no_ops:
        # still prove the current dataset is valid and matches the
        # delta's predicted result hash
        bad = dmanifest.verify_manifest(ds, man)
        if bad:
            raise DeltaError("existing dataset fails manifest: "
                             + "; ".join(bad))
        result_hash = dmanifest.corpus_hash(
            {t: parquetio.logical_hash(t, merged[t])
             for t in dschema.TABLE_ORDER})
        if result_hash != delta["result_corpus_logical_sha256"]:
            raise DeltaError("NO_CHANGE delta result hash mismatch")
        return {"status": "NO_CHANGE",
                "corpus_logical_sha256": base_hash,
                "delta_id": delta["delta_id"]}

    # full integrity gate BEFORE any write
    errs = dint.check(merged) + uint.check_update_invariants(merged)
    if errs:
        raise DeltaError("merged state violates integrity: "
                         + "; ".join(errs[:8]))

    staging = ds.parent / f"{ds.name}.staging-{delta['delta_id'][7:19]}"
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
        man1 = dmanifest.build_manifest(
            inputs={
                "base_dataset": {"corpus_logical_sha256": base_hash},
                "delta": {"delta_id": delta["delta_id"],
                          "observation_id": delta["observation_id"],
                          "observation_sha256":
                              delta["observation_sha256"]},
                "update": {"engine": "opencnmv.update",
                           "delta_format": delta_mod.DELTA_FORMAT}},
            tables=table_meta, code_commit=code_commit,
            generator=generator or {"tool": "opencnmv.update.apply_delta"},
            params={"compression": "zstd",
                    "row_order": "canonical sorted",
                    "update_mode": "delta-apply (append-only canonical "
                                   "rows; explicit metadata updates)"},
            findings=[f"applied {delta['observation_id']} via "
                      f"{delta['delta_id']}"],
            limitations=man.get("limitations", []))
        write_canonical(man1, staging / "dataset_manifest.json")
        bad = dmanifest.verify_manifest(staging, man1)
        if bad:
            raise DeltaError("staged dataset fails manifest: "
                             + "; ".join(bad))
        if man1["corpus_logical_sha256"] != \
                delta["result_corpus_logical_sha256"]:
            raise DeltaError("staged corpus hash != delta prediction")
        if fail_hook == "before_publish":
            raise RuntimeError("injected failure: before_publish")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # publish: two-renames swap; original kept as .prev until success
    prev = ds.parent / f"{ds.name}.prev-{delta['delta_id'][7:19]}"
    if prev.exists():
        shutil.rmtree(prev)
    os.rename(ds, prev)
    try:
        os.rename(staging, ds)
    except BaseException:
        os.rename(prev, ds)
        raise
    shutil.rmtree(prev, ignore_errors=True)
    return {"status": "APPLIED",
            "corpus_logical_sha256": man1["corpus_logical_sha256"],
            "delta_id": delta["delta_id"],
            "transitions": len(delta["transitions"])}
