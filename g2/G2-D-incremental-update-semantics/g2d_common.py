"""Shared helpers for the G2-D gate: dataset decompilation, carving,
dataset writing, and the independent observation-union oracle.

Gate code only — never imported by src/. The production update engine
under test lives in opencnmv.update.
"""
from __future__ import annotations

import json
from pathlib import Path

from opencnmv.dataset import manifest as dmanifest
from opencnmv.dataset import parquetio, schema as dschema, tables as dtables
from opencnmv.serialize import write_canonical
from opencnmv.update import classify as ucls

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "_out"
G2C_DS = (REPO / "g2" / "G2-C-columnar-dataset-v1" / "_out" / "runA"
          / "dataset" / "v1")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_tables(ds: Path) -> dict[str, list[dict]]:
    import pyarrow.parquet as pq
    return {t: pq.read_table(ds / f"{t}.parquet").to_pylist()
            for t in dschema.TABLE_ORDER}


def write_dataset(ds: Path, tbl: dict[str, list[dict]],
                  inputs: dict | None = None) -> dict:
    """Materialize a row set to a dataset dir (Parquet + schema +
    manifest) using the same deterministic writer as production."""
    ds.mkdir(parents=True, exist_ok=True)
    meta = {}
    for t in dschema.TABLE_ORDER:
        rows = sorted(tbl[t], key=parquetio.ROW_ORDER[t])
        meta[t] = parquetio.write_table(t, rows, ds / f"{t}.parquet")
    (ds / "schema").mkdir(exist_ok=True)
    for t in dschema.TABLE_ORDER:
        write_canonical(dschema.schema_dict(t),
                        ds / "schema" / f"{t}.schema.json")
    man = dmanifest.build_manifest(
        inputs=inputs or {}, tables=meta, code_commit="g2d",
        generator={"tool": "g2d_common.write_dataset"},
        params={"compression": "zstd", "row_order": "canonical sorted"})
    write_canonical(man, ds / "dataset_manifest.json")
    return man


# --- decompile: dataset rows -> observation filing entries -------------------

def decompile(tables: dict[str, list[dict]]) -> dict[str, dict]:
    """Rebuild the CANONICAL_OBSERVATION_V1 filing entries implied by a
    materialized dataset. Inverse of the materialization: filing objects
    via filing_from_rows (byte-exact, proven in G2-C), event-owned
    artifacts, mapping files from record_json, and fact states from the
    fact plane."""
    out: dict[str, dict] = {}
    for frow in tables["filing"]:
        fid = frow["filing_id"]
        scoped = ucls.filing_scoped_rows(tables, fid)
        fx = dtables.filing_from_rows(
            frow, scoped["filing_version"], scoped["submission_variant"],
            scoped["variant_version"], scoped["view_resolution"],
            scoped["version_event"], scoped["event_affects"],
            [a for a in scoped["artifact"]
             if a["owner_kind"] != "version_event"],
            scoped["extension_mapping"])
        entry: dict = {"filing": fx}
        # extras must be supplied verbatim: fixture overlays may carry
        # schema-key-named fields (e.g. a fixture-scoped
        # "extension_mappings" list) that filing_rows would otherwise
        # drop when re-deriving extras from non-schema keys
        if frow["extras_json"]:
            entry["extras"] = json.loads(frow["extras_json"])
        extra = [{"event_id": a["owner_id"],
                  "artifact": {k: v for k, v in
                               (("artifact_id", a["artifact_id"]),
                                ("role", a["role"]),
                                ("sha256", a["sha256"]),
                                ("bytes", a["bytes"]),
                                ("media_type", a["media_type"]),
                                ("source_url", a["source_url"]),
                                ("package_lang_tag",
                                 a["package_lang_tag"])) if v is not None
                               or k == "package_lang_tag"}}
                 for a in scoped["artifact"]
                 if a["owner_kind"] == "version_event"]
        if extra:
            entry["extra_artifacts"] = sorted(
                extra, key=lambda e: e["event_id"])  # rows already in
            # artifact_ordinal order within each owner
        by_file: dict[str, list[dict]] = {}
        for m in scoped["extension_mapping"]:
            by_file.setdefault(m["source_file"], []).append(m)
        mfiles = []
        for sf, rows in sorted(by_file.items()):
            rows.sort(key=lambda r: r["source_ordinal"])
            mfiles.append({
                "source_file": sf,
                "source_lang":
                    rows[0]["source_variant_id"].rsplit("#", 1)[1],
                "target_lang":
                    rows[0]["target_variant_id"].rsplit("#", 1)[1],
                "records": [json.loads(r["record_json"]) for r in rows]})
        if mfiles:
            entry["extension_mapping_files"] = mfiles
        states = []
        for prov in sorted(scoped["provenance"],
                           key=lambda r: r["state_id"]):
            sid, vvid = prov["state_id"], prov["variant_version_id"]
            frows = sorted((r for r in scoped["facts"]
                            if r["state_id"] == sid),
                           key=lambda r: r["seq"])
            dims_by_fact: dict[str, list[dict]] = {}
            for d in scoped["fact_dimension"]:
                dims_by_fact.setdefault(d["fact_id"], []).append(d)
            recs, units = [], []
            for r in frows:
                recs.append(dtables.record_from_row(
                    r, dims_by_fact.get(r["fact_id"], [])))
                units.append({
                    "num": (r["unit_numerator"].split("*")
                            if r["unit_numerator"] else []),
                    "den": (r["unit_denominator"].split("*")
                            if r["unit_denominator"] else [])})
            states.append({
                "state_id": sid, "variant_version_id": vvid,
                "profile": frows[0]["profile"] if frows else "esef",
                "facts": recs, "units": units,
                "provenance": {k: v for k, v in prov.items()
                               if k not in ("state_id", "filing_id",
                                            "variant_version_id")}})
        if states:
            entry["states"] = states
        out[fid] = entry
    return out


def obs_doc(entries: list[dict], obs_id: str,
            captured_at: str | None = None) -> dict:
    from opencnmv.update import observe as uobs
    doc = {"observation_format": uobs.OBSERVATION_FORMAT,
           "observation_id": obs_id, "captured_at": captured_at,
           "filings": entries}
    doc["observation_sha256"] = uobs.observation_sha256(doc)
    return doc


# --- carve --------------------------------------------------------------------

def deep_tables(tables: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Deep copy of a table row set — carves must never alias the base."""
    return {t: [dict(r) for r in rows] for t, rows in tables.items()}


def subtract(tables: dict[str, list[dict]], table: str,
             pred) -> dict[str, list[dict]]:
    """Return a copy of tables with rows matching pred removed."""
    out = deep_tables(tables)
    out[table] = [r for r in out[table] if not pred(r)]
    return out


def carve_filing(tables: dict[str, list[dict]],
                 filing_id: str) -> dict[str, list[dict]]:
    """Remove every row scoped to a filing (fresh-corpus-minus-filing)."""
    scoped = ucls.filing_scoped_rows(tables, filing_id)
    drop = {t: {json.dumps(r, sort_keys=True, default=str)
                for r in rows} for t, rows in scoped.items()}
    return {t: [r for r in tables[t]
                if json.dumps(r, sort_keys=True, default=str)
                not in drop[t]] for t in tables}


# --- independent oracle -------------------------------------------------------
#
# Rebuilds the expected S1 row set from the observation *sequence* alone:
# each observation's projected rows are merged into an accumulator by
# primary key. Ledger policy (independent re-expression, not a call into
# update.classify merge): identical re-observation is a no-op; the narrow
# UPDATABLE surfaces may move; anything else under an existing identity
# is an oracle inconsistency (the scenario is then invalid, not PASS).

def oracle_materialize(obs_docs: list[dict]) -> dict[str, list[dict]]:
    acc: dict[str, dict] = {t: {} for t in dschema.TABLE_ORDER}

    def merge(table: str, row: dict):
        pk = ucls.PK[table](row)
        old = acc[table].get(pk)
        if old is None:
            acc[table][pk] = row
        elif old != row:
            changed = {k for k in set(old) | set(row)
                       if old.get(k) != row.get(k)}
            updatable = {f for t, f in ucls.UPDATABLE if t == table}
            if not changed <= updatable:
                raise AssertionError(
                    f"oracle: conflicting rows under {table} {pk}: "
                    f"{sorted(changed)}")
            merged = dict(old)
            merged.update({k: row[k] for k in changed})
            acc[table][pk] = merged

    for obs in obs_docs:
        for fobs in obs["filings"]:
            fid = fobs["filing"]["filing_id"]
            rows = ucls.observed_filing_rows(fobs)
            for t in ucls.MODEL_DIFF_TABLES:
                for r in rows[t]:
                    merge(t, r)
            for st in fobs.get("states", []):
                seq_rows, dim_rows, prov = ucls._state_rows(st, fid)
                for r in seq_rows:
                    merge("facts", r)
                for r in dim_rows:
                    merge("fact_dimension", r)
                merge("provenance", prov)
    return {t: [acc[t][k] for k in sorted(
                acc[t], key=lambda k: parquetio.ROW_ORDER[t](acc[t][k]))]
            for t in dschema.TABLE_ORDER}
