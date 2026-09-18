"""Deterministic delta document: plan(S0, O1) -> delta.

The delta is self-contained, canonical-JSON hashable, and bound to a
base state: it records the transitions, every row op, and the predicted
result corpus hash. Applying it to any base whose logical hash differs
from ``base_corpus_logical_sha256`` must fail (stale-base control).

    {
      "delta_format": "CANONICAL_DELTA_V1",
      "delta_id": "sha256:...",
      "base_corpus_logical_sha256": "...",
      "observation_id": "...", "observation_sha256": "...",
      "transitions": [...],
      "rows_added":   {table: [row, ...]},
      "rows_updated": {table: [{"pk": [...], "before": row,
                              "after": row}]},
      "rows_removed": {table: [row, ...]},
      "result_corpus_logical_sha256": "...",   // predicted S1 hash
      "stats": {...}
    }
"""
from __future__ import annotations

import hashlib
import json

from opencnmv.dataset import manifest as dmanifest
from opencnmv.dataset import parquetio
from opencnmv.dataset import schema as dschema
from opencnmv.serialize import canonical_bytes
from opencnmv.update import classify as classify_mod
from opencnmv.update import observe as observe_mod

DELTA_FORMAT = "CANONICAL_DELTA_V1"


def _sort_rows(table: str, rows: list[dict]) -> list[dict]:
    return sorted(rows, key=parquetio.ROW_ORDER[table])


def merged_tables(base: dict[str, list[dict]], delta_ops: dict) \
        -> dict[str, list[dict]]:
    """Pure merge: base + added - removed, updates applied by PK."""
    merged = {t: list(base.get(t, [])) for t in dschema.TABLE_ORDER}
    for t, rows in delta_ops["removed"].items():
        drop = {classify_mod.PK[t](r) for r in rows}
        merged[t] = [r for r in merged[t]
                     if classify_mod.PK[t](r) not in drop]
    for t, ups in delta_ops["updated"].items():
        amap = {tuple(u["pk"]): u["after"] for u in ups}
        merged[t] = [amap.get(classify_mod.PK[t](r), r)
                     for r in merged[t]]
    for t, rows in delta_ops["added"].items():
        merged[t].extend(rows)
    return {t: _sort_rows(t, merged[t]) for t in dschema.TABLE_ORDER}


def plan(base_tables: dict[str, list[dict]], obs: dict,
         base_corpus_logical_sha256: str) -> dict:
    """Compute the canonical delta for (S0, O1). Pure; no I/O."""
    # normalize dict key order: a document assembled in memory (insertion
    # order) and the same document round-tripped through a sorted-keys
    # writer must plan identically — record_json cells preserve their
    # dict's key order verbatim.
    obs = json.loads(json.dumps(obs, ensure_ascii=False, sort_keys=True))
    observe_mod.verify_self_consistency(obs)
    res = classify_mod.classify(base_tables, obs)
    ops = {"added": {t: _sort_rows(t, res["added"][t])
                     for t in dschema.TABLE_ORDER},
           "updated": {t: sorted(res["updated"][t],
                                 key=lambda u: u["pk"])
                       for t in dschema.TABLE_ORDER},
           "removed": {t: _sort_rows(t, [])
                       for t in dschema.TABLE_ORDER}}
    merged = merged_tables(base_tables, ops)
    result_hash = dmanifest.corpus_hash(
        {t: parquetio.logical_hash(t, merged[t])
         for t in dschema.TABLE_ORDER})
    delta = {
        "delta_format": DELTA_FORMAT,
        "base_corpus_logical_sha256": base_corpus_logical_sha256,
        "observation_id": obs["observation_id"],
        "observation_sha256": observe_mod.observation_sha256(obs),
        "transitions": res["transitions"],
        "unresolved": res["unresolved"],
        "rows_added": ops["added"],
        "rows_updated": ops["updated"],
        "rows_removed": ops["removed"],
        "result_corpus_logical_sha256": result_hash,
        "stats": {
            "rows_added": {t: len(ops["added"][t])
                           for t in dschema.TABLE_ORDER},
            "rows_updated": {t: len(ops["updated"][t])
                             for t in dschema.TABLE_ORDER},
            "rows_removed": {t: 0 for t in dschema.TABLE_ORDER},
            "transitions": len(res["transitions"]),
            "facts_added_rows": len(ops["added"]["facts"]),
        },
    }
    payload = {k: v for k, v in delta.items()}
    delta["delta_id"] = "sha256:" + hashlib.sha256(
        canonical_bytes(payload)).hexdigest()
    return delta


def verify_delta(delta: dict) -> list[str]:
    """Structural + self-hash verification of a delta document."""
    err: list[str] = []
    if delta.get("delta_format") != DELTA_FORMAT:
        err.append(f"delta_format != {DELTA_FORMAT}")
    payload = {k: v for k, v in delta.items() if k != "delta_id"}
    want = "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()
    if delta.get("delta_id") != want:
        err.append("delta_id self-hash mismatch (tampered or malformed)")
    for k in ("base_corpus_logical_sha256",
              "result_corpus_logical_sha256", "observation_sha256",
              "observation_id", "transitions", "rows_added",
              "rows_updated", "rows_removed"):
        if k not in delta:
            err.append(f"missing {k}")
    for t in delta.get("rows_added", {}):
        if t not in dschema.SCHEMAS:
            err.append(f"unknown table in rows_added: {t}")
        else:
            cols = {f.name for f in dschema.SCHEMAS[t]}
            for r in delta["rows_added"][t]:
                extra = set(r) - cols
                if extra:
                    err.append(f"{t}: row has unknown columns {extra}")
    return err


def delta_bytes(delta: dict) -> bytes:
    return canonical_bytes(delta)
