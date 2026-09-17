"""Change classification: (S0 table rows, observation) -> transitions +
row-level operations.

The classifier is pure and deterministic. It never mutates inputs and
never invents state: anything the evidence cannot justify is classified
UNRESOLVED / SOURCE_STATE_CONFLICT and produces no row ops for that
filing.

Row-operation policy (Canonical Model V1 is an evidence ledger):

  * canonical rows are APPEND-ONLY. A superseded version's artifacts or
    facts are historical capture records and are never deleted.
    ARTIFACT_REMOVED / FACT_REMOVED are semantic transitions ("absent
    from the newer version's set"), not row deletions.
  * two narrow metadata surfaces may be updated in place, always
    recorded in the delta:
      - variant_version.created_by_event_id: None -> event
        (backfill when the creating event is discovered later)
      - extension_mapping verdict payload at the same
        (filing_id, source_file, source_ordinal) key (analysis metadata
        evolution — old content preserved in the delta's `before`)
  * rows_removed is emitted only for rows that were never canonical
    history (currently unused; reserved).
  * every other content difference under an existing identity is a
    SOURCE_STATE_CONFLICT — never silently applied.
"""
from __future__ import annotations

import json

from opencnmv.canonicalize import extension_mapping as xmap
from opencnmv.canonicalize import facts as xfacts
from opencnmv.dataset import tables as dtables
from opencnmv.update import transitions as T

# PK selectors per table (must match dataset.integrity primary keys).
PK = {
    "filing": lambda r: (r["filing_id"],),
    "filing_version": lambda r: (r["filing_version_id"],),
    "submission_variant": lambda r: (r["variant_id"],),
    "variant_version": lambda r: (r["variant_version_id"],),
    "view_resolution": lambda r: (r["filing_id"],
                                  r["requested_ui_language"]),
    "version_event": lambda r: (r["event_id"],),
    "event_affects": lambda r: (r["event_id"], r["affects_ordinal"]),
    "artifact": lambda r: (r["owner_kind"], r["owner_id"],
                           r["artifact_ordinal"]),
    "extension_mapping": lambda r: (r["filing_id"], r["source_file"],
                                    r["source_ordinal"]),
    "provenance": lambda r: (r["state_id"],),
    "facts": lambda r: (r["fact_id"],),
    "fact_dimension": lambda r: (r["fact_id"], r["dim_qname"]),
}

MODEL_DIFF_TABLES = ("filing", "filing_version", "submission_variant",
                     "variant_version", "view_resolution", "version_event",
                     "event_affects", "artifact", "extension_mapping")

# Fields allowed to change in place under an existing PK.
UPDATABLE = {
    ("variant_version", "created_by_event_id"),
    ("extension_mapping", "pair_id"),
    ("extension_mapping", "target_variant_id"),
    ("extension_mapping", "source_qname"),
    ("extension_mapping", "target_qname"),
    ("extension_mapping", "mapping_type"),
    ("extension_mapping", "verdict"),
    ("extension_mapping", "rewrites_identity"),
    ("extension_mapping", "record_json"),
}


def _pk(table: str, row: dict) -> tuple:
    return PK[table](row)


def filing_scoped_rows(tables: dict[str, list[dict]],
                       filing_id: str) -> dict[str, list[dict]]:
    """All base rows belonging to one filing, across every table."""
    vv_ids = {r["variant_version_id"] for r in tables["variant_version"]
              if r["variant_id"].startswith(filing_id + "#")}
    fv_ids = {r["filing_version_id"] for r in tables["filing_version"]
              if r["filing_id"] == filing_id}
    ev_ids = {r["event_id"] for r in tables["version_event"]
              if r["filing_id"] == filing_id}
    owners = vv_ids | fv_ids | ev_ids
    fact_ids = {r["fact_id"] for r in tables["facts"]
                if r["variant_version_id"] in vv_ids}
    return {
        "filing": [r for r in tables["filing"] if r["filing_id"] == filing_id],
        "filing_version": [r for r in tables["filing_version"]
                           if r["filing_id"] == filing_id],
        "submission_variant": [r for r in tables["submission_variant"]
                               if r["filing_id"] == filing_id],
        "variant_version": [r for r in tables["variant_version"]
                            if r["variant_id"] in
                            {v["variant_id"] for v in
                             tables["submission_variant"]
                             if v["filing_id"] == filing_id}],
        "view_resolution": [r for r in tables["view_resolution"]
                            if r["filing_id"] == filing_id],
        "version_event": [r for r in tables["version_event"]
                          if r["filing_id"] == filing_id],
        "event_affects": [r for r in tables["event_affects"]
                          if r["event_id"] in ev_ids],
        "artifact": [r for r in tables["artifact"]
                     if r["owner_id"] in owners],
        "extension_mapping": [r for r in tables["extension_mapping"]
                              if r["filing_id"] == filing_id],
        "provenance": [r for r in tables["provenance"]
                       if r["filing_id"] == filing_id],
        "facts": [r for r in tables["facts"]
                  if r["variant_version_id"] in vv_ids],
        "fact_dimension": [r for r in tables["fact_dimension"]
                           if r["fact_id"] in fact_ids],
    }


def observed_filing_rows(fobs: dict) -> dict[str, list[dict]]:
    """Table rows implied by one observation filing entry."""
    fx = fobs["filing"]
    fid = fx["filing_id"]
    rows = dtables.filing_rows(fx, extras=fobs.get("extras"))
    per_owner: dict[str, int] = {}
    for ea in fobs.get("extra_artifacts", []):
        i = per_owner.get(ea["event_id"], 0)
        per_owner[ea["event_id"]] = i + 1
        rows["artifact"].append(dtables._artifact_row(
            "version_event", ea["event_id"], i, ea["artifact"]))
    for mf in fobs.get("extension_mapping_files", []):
        rows["extension_mapping"].extend(dtables.mapping_rows(
            fid, mf.get("source_lang", "es"), mf.get("target_lang", "en"),
            mf["records"], mf["source_file"]))
    return rows


def _struct_key(row: dict) -> tuple:
    """Fact structural identity (no payload, no ids)."""
    return (row["concept"], row["entity_scheme"], row["entity"],
            row["period_start"], row["period_end"], row["period_instant"],
            row["period_forever"], row["unit"], row["lang"],
            row["canonical_dims_json"])


def _fact_transitions(fid: str, vvid: str, supersedes: str | None,
                      new_fact_rows: list[dict],
                      old_fact_rows: list[dict]) -> list[dict]:
    """Classify fact-level change between the new version and its
    predecessor. Facts themselves are appended under the new
    variant_version; these transitions describe the semantic delta."""
    if supersedes is None:
        if new_fact_rows:
            return [T.transition(T.FACT_ADDED, fid,
                                 variant_version_id=vvid,
                                 count=len(new_fact_rows))]
        return []
    old_by_key: dict[tuple, list[dict]] = {}
    for r in old_fact_rows:
        old_by_key.setdefault(_struct_key(r), []).append(r)
    new_keys = [_struct_key(r) for r in new_fact_rows]
    added = removed = changed = 0
    matched: set[tuple] = set()
    for r, k in zip(new_fact_rows, new_keys):
        olds = old_by_key.get(k) or []
        same = [o for o in olds if o["value_sha256"] == r["value_sha256"]
                and o["xValue_sha256"] == r["xValue_sha256"]
                and o["isNil"] == r["isNil"]]
        if same:
            matched.add(k)
        elif olds:
            changed += 1
            matched.add(k)
        else:
            added += 1
    removed = len(old_fact_rows) - sum(
        len(old_by_key[k]) for k in matched)
    out = []
    if added:
        out.append(T.transition(T.FACT_ADDED, fid, variant_version_id=vvid,
                                count=added))
    if removed:
        out.append(T.transition(T.FACT_REMOVED, fid, variant_version_id=vvid,
                                count=removed))
    if changed:
        out.append(T.transition(T.FACT_PAYLOAD_CHANGED, fid,
                                variant_version_id=vvid, count=changed))
    return out


def classify_filing(tables: dict[str, list[dict]],
                    fobs: dict) -> dict:
    """Classify one filing observation against base tables.

    Returns {"transitions": [...], "added": {t: [rows]},
             "updated": {t: [{"pk","before","after"}]},
             "unresolved": bool}
    Unresolved/conflict filings produce zero row ops.
    """
    fx = fobs["filing"]
    fid = fx["filing_id"]
    out: dict = {"transitions": [], "added": {t: [] for t in PK},
                 "updated": {t: [] for t in PK}, "unresolved": False}
    tr = out["transitions"]

    old = filing_scoped_rows(tables, fid)
    new = observed_filing_rows(fobs)
    dispositions = fobs.get("artifact_dispositions", {}) or {}
    known_events = {r["event_id"] for r in old["version_event"]}

    def conflict(msg: str, **detail):
        out["unresolved"] = True
        tr.append(T.transition(T.SOURCE_STATE_CONFLICT, fid, reason=msg,
                               **detail))

    is_new_filing = not old["filing"]
    if is_new_filing:
        tr.append(T.transition(T.NEW_FILING, fid,
                               registro=fx["registro_oficial"],
                               family=fx["family"]))

    for tname in MODEL_DIFF_TABLES:
        old_by_pk = {_pk(tname, r): r for r in old[tname]}
        new_by_pk = {_pk(tname, r): r for r in new[tname]}
        # duplicate PK inside the observation is an observation defect
        if len(new_by_pk) != len(new[tname]):
            conflict(f"duplicate identity inside observation: {tname}")
            continue
        for pk, nrow in new_by_pk.items():
            orow = old_by_pk.get(pk)
            if orow is None:
                continue                       # handled as added below
            if orow == nrow:
                continue                       # unchanged
            # same identity, different content
            if tname == "variant_version" and set(
                    k for k in nrow if nrow[k] != orow[k]) == {
                    "created_by_event_id"} and \
                    orow["created_by_event_id"] is None:
                out["updated"][tname].append(
                    {"pk": list(pk), "before": orow, "after": nrow})
                continue
            if tname == "extension_mapping":
                diff = {k for k in nrow if nrow[k] != orow[k]}
                if diff <= {f for t, f in UPDATABLE if t == tname}:
                    nrow = dict(nrow)
                    nrow["rewrites_identity"] = \
                        nrow["verdict"] == xmap.PROVEN
                    out["updated"][tname].append(
                        {"pk": list(pk), "before": orow, "after": nrow})
                    tr.append(T.transition(
                        T.EXTENSION_MAPPING_CHANGED, fid,
                        key=list(pk), verdict_before=orow["verdict"],
                        verdict_after=nrow["verdict"]))
                    continue
            conflict(f"{tname} content changed under existing identity",
                     pk=list(pk))
        added_rows = [new_by_pk[pk] for pk in new_by_pk
                      if pk not in old_by_pk]
        removed_rows = [old_by_pk[pk] for pk in old_by_pk
                        if pk not in new_by_pk]

        if tname == "filing_version" and added_rows:
            for r in added_rows:
                tr.append(T.transition(T.NEW_FILING_VERSION, fid,
                                       filing_version_id=
                                       r["filing_version_id"],
                                       source_nreg=r["source_nreg"],
                                       submission_kind=
                                       r["submission_kind"]))
        elif tname == "submission_variant" and added_rows:
            for r in added_rows:
                # a new variant must carry genuinely distinct content:
                # identical artifact_set to a sibling variant is the
                # UI-fallback/mislabel shape, not a real submission
                new_vvs = [v for v in new["variant_version"]
                           if v["variant_id"] == r["variant_id"]]
                asids = {v["artifact_set_id"] for v in new_vvs
                         if v["artifact_set_id"]}
                sibling_asids = {v["artifact_set_id"]
                                 for v in old["variant_version"]
                                 if v["artifact_set_id"]}
                if asids and asids <= sibling_asids:
                    conflict("new variant reuses an existing variant's "
                             "artifact_set_id — indistinguishable from a "
                             "UI-language fallback",
                             variant_id=r["variant_id"])
                    continue
                tr.append(T.transition(T.NEW_SUBMISSION_VARIANT, fid,
                                       variant_id=r["variant_id"],
                                       submission_language=
                                       r["submission_language"]))
        elif tname == "variant_version" and added_rows:
            existing_vvids = {r["variant_version_id"]
                              for r in old["variant_version"]}
            for r in sorted(added_rows, key=lambda x: x["version_seq"]):
                sup = r["supersedes_variant_version_id"]
                if sup is not None and sup not in existing_vvids and \
                        sup not in {a["variant_version_id"]
                                    for a in added_rows}:
                    conflict("variant_version supersedes unknown version",
                             variant_version_id=r["variant_version_id"],
                             supersedes=sup)
                    continue
                tr.append(T.transition(T.NEW_VARIANT_VERSION, fid,
                                       variant_version_id=
                                       r["variant_version_id"],
                                       variant_id=r["variant_id"],
                                       observed=r["observed"],
                                       supersedes=sup))
                # artifact-level transitions vs the superseded set
                old_arts = {a["artifact_id"]: a for a in old["artifact"]
                            if a["owner_id"] == sup} if sup else {}
                new_arts = {a["artifact_id"]: a for a in new["artifact"]
                            if a["owner_id"] == r["variant_version_id"]}
                for aid in sorted(set(new_arts) - set(old_arts)):
                    tr.append(T.transition(T.ARTIFACT_ADDED, fid,
                                           artifact_id=aid,
                                           owner=r["variant_version_id"]))
                for aid in sorted(set(old_arts) & set(new_arts)):
                    if old_arts[aid]["sha256"] != new_arts[aid]["sha256"]:
                        tr.append(T.transition(
                            T.ARTIFACT_CHANGED, fid, artifact_id=aid,
                            owner=r["variant_version_id"]))
                for aid in sorted(set(old_arts) - set(new_arts)):
                    tr.append(T.transition(T.ARTIFACT_REMOVED, fid,
                                           artifact_id=aid,
                                           owner=r["variant_version_id"]))
        elif tname == "view_resolution" and added_rows:
            for r in added_rows:
                tr.append(T.transition(
                    T.VIEW_RESOLUTION_RECORDED, fid,
                    requested_ui_language=r["requested_ui_language"],
                    resolved_variant_id=r["resolved_variant_id"],
                    resolution_mode=r["resolution_mode"]))
        elif tname == "version_event" and added_rows:
            new_affects = [a for a in new["event_affects"]
                           if a["event_id"] in
                           {r["event_id"] for r in added_rows}]
            for r in added_rows:
                tr.append(T.transition(T.NEW_VERSION_EVENT, fid,
                                       event_id=r["event_id"],
                                       event_type=r["event_type"],
                                       event_date=r["event_date"],
                                       source_nreg=r["source_nreg"],
                                       scope_status=r["scope_status"]))
                aff = [a for a in new_affects
                       if a["event_id"] == r["event_id"]]
                if any(a["variant_id"] for a in aff):
                    tr.append(T.transition(
                        T.VARIANT_SCOPED_VERSION_EVENT, fid,
                        event_id=r["event_id"],
                        variants=sorted({a["variant_id"] for a in aff
                                         if a["variant_id"]})))
                if r["scope_status"] == "VARIANT_SCOPE_NOT_OBSERVABLE":
                    tr.append(T.transition(
                        T.FILING_SCOPE_NOT_OBSERVABLE, fid,
                        event_id=r["event_id"]))
        elif tname == "artifact":
            # artifacts owned by entities that are themselves new in this
            # delta fold into the parent transition; only artifacts added
            # to an already-recorded owner are reported separately
            old_owner_ids = ({r["filing_version_id"]
                              for r in old["filing_version"]}
                             | {r["variant_version_id"]
                                for r in old["variant_version"]}
                             | {r["event_id"]
                                for r in old["version_event"]})
            for r in added_rows:
                if r["owner_id"] in old_owner_ids:
                    tr.append(T.transition(T.ARTIFACT_ADDED, fid,
                                           artifact_id=r["artifact_id"],
                                           owner=r["owner_id"]))
        elif tname == "extension_mapping" and added_rows:
            # recompute rewrites_identity from verdict — never trust input
            for r in added_rows:
                r["rewrites_identity"] = r["verdict"] == xmap.PROVEN
            tr.append(T.transition(T.EXTENSION_MAPPING_ADDED, fid,
                                   count=len(added_rows)))
        elif tname == "event_affects" and added_rows:
            # affects rows for an already-recorded event mutate history
            foreign = [a for a in added_rows
                       if a["event_id"] in known_events]
            if foreign:
                conflict("event_affects appended to a recorded event",
                         event_ids=sorted({a["event_id"]
                                           for a in foreign}))
                added_rows = [a for a in added_rows
                              if a["event_id"] not in known_events]
        if removed_rows:
            if tname == "artifact":
                for r in removed_rows:
                    disp = dispositions.get(r["artifact_id"]) or {}
                    if disp.get("status") == "REMOVED_CONFIRMED":
                        tr.append(T.transition(
                            T.ARTIFACT_REMOVED, fid,
                            artifact_id=r["artifact_id"],
                            owner=r["owner_id"],
                            evidence=disp.get("evidence")))
                        # historical row is retained: append-only ledger
                    else:
                        out["unresolved"] = True
                        tr.append(T.transition(
                            T.UNRESOLVED, fid,
                            reason="artifact absent from observation "
                                   "without removal evidence",
                            artifact_id=r["artifact_id"],
                            owner=r["owner_id"]))
            else:
                for r in removed_rows:
                    out["unresolved"] = True
                    tr.append(T.transition(
                        T.UNRESOLVED, fid,
                        reason=f"{tname} row absent from observation; "
                               "history cannot shrink",
                        pk=list(_pk(tname, r))))
        out["added"][tname] = added_rows if not out["unresolved"] else []

    if out["unresolved"]:
        for tname in MODEL_DIFF_TABLES:
            out["added"][tname] = []
            out["updated"][tname] = []
        return out

    # ---- fact states -------------------------------------------------
    old_vvids = {r["variant_version_id"] for r in old["variant_version"]}
    new_vvids = {r["variant_version_id"]
                 for r in out["added"]["variant_version"]}
    old_facts_by_vv: dict[str, list[dict]] = {}
    for r in old["facts"]:
        old_facts_by_vv.setdefault(r["variant_version_id"], []).append(r)
    old_state_ids = {r["state_id"] for r in old["provenance"]}

    for st in fobs.get("states", []):
        vvid = st["variant_version_id"]
        sid = st["state_id"]
        if vvid in old_vvids:
            seq_rows, dim_rows, prov = _state_rows(st, fid)
            old_seq = [r for r in old["facts"] if r["state_id"] == sid]
            old_fids = {r["fact_id"] for r in old_seq}
            old_dim = [r for r in old["fact_dimension"]
                       if r["fact_id"] in old_fids]
            old_prov = [r for r in old["provenance"]
                        if r["state_id"] == sid]
            identical = (_same_rows(old_seq, seq_rows)
                         and _same_rows(old_dim, dim_rows)
                         and _same_rows(old_prov, [prov]))
            if sid in old_state_ids:
                # identical resubmission is an idempotent replay; differing
                # bytes under a recorded state_id are a source conflict
                if not identical:
                    conflict("recorded state resubmitted with different "
                             "content", state_id=sid)
            else:
                out["unresolved"] = True
                tr.append(T.transition(
                    T.UNRESOLVED, fid,
                    reason="new state_id for an existing variant_version",
                    state_id=sid, variant_version_id=vvid))
            continue
        if vvid not in new_vvids:
            out["unresolved"] = True
            tr.append(T.transition(
                T.UNRESOLVED, fid,
                reason="facts supplied for a variant_version the "
                       "observation does not introduce",
                variant_version_id=vvid))
            continue
        sup = next((r["supersedes_variant_version_id"]
                    for r in new["variant_version"]
                    if r["variant_version_id"] == vvid), None)
        seq_rows, dim_rows, prov = _state_rows(st, fid)
        out["added"]["facts"].extend(seq_rows)
        out["added"]["fact_dimension"].extend(dim_rows)
        tr.extend(_fact_transitions(
            fid, vvid, sup, seq_rows,
            old_facts_by_vv.get(sup, []) if sup else []))
        out["added"]["provenance"].append(prov)

    if not any(out["added"].values()) and not any(out["updated"].values()) \
            and not tr:
        tr.append(T.transition(T.NO_CHANGE, fid))
    return out


def _state_rows(st: dict, fid: str) -> tuple[list, list, dict]:
    """Deterministic fact/dimension/provenance rows for one state."""
    vvid, sid = st["variant_version_id"], st["state_id"]
    recs = st["facts"]
    units = st.get("units") or [{} for _ in recs]
    seq_rows, dim_rows = [], []
    occ: dict[str, int] = {}
    for seq, rec in enumerate(recs):
        rec = dict(rec)
        rec.setdefault("_profile", st.get("profile", "esef"))
        base = xfacts.fact_id(canonical_key_of(rec), vvid)
        n = occ.get(base, 0)
        occ[base] = n + 1
        fact_id = base if n == 0 else f"{base}#{n}"
        row, dims = dtables.fact_rows(
            rec, vvid, sid, seq, fact_id,
            unit_measures=(units[seq].get("num", []),
                           units[seq].get("den", [])))
        seq_rows.append(row)
        dim_rows.extend(dims)
    prov = dict(st["provenance"])
    prov["state_id"] = sid
    prov["filing_id"] = fid
    prov["variant_version_id"] = vvid
    return seq_rows, dim_rows, prov


def _same_rows(old: list[dict], new: list[dict]) -> bool:
    """Multiset equality of row dicts (order-insensitive)."""
    def enc(r: dict) -> str:
        return json.dumps(r, sort_keys=True, ensure_ascii=False,
                          default=str)
    return sorted(map(enc, old)) == sorted(map(enc, new))


def canonical_key_of(rec: dict) -> dict:
    """Same structural key as the G2-C materializer."""
    if rec.get("period_start"):
        period = f"{rec['period_start']}/{rec['period_end']}"
    elif rec.get("period_instant"):
        period = rec["period_instant"]
    else:
        period = "forever"
    entity = "|".join(x for x in (rec.get("entity_scheme"),
                                  rec.get("entity")) if x)
    return {"concept": rec["concept"], "entity": entity, "period": period,
            "dimensions": rec.get("dimensions") or {},
            "unit": rec.get("unit"), "language": rec.get("lang")}


def classify(tables: dict[str, list[dict]], obs: dict) -> dict:
    """Classify a whole observation. Returns {"transitions", "added",
    "updated", "unresolved"} merged across filings."""
    transitions: list[dict] = []
    added: dict[str, list] = {t: [] for t in PK}
    updated: dict[str, list] = {t: [] for t in PK}
    unresolved = False
    for fobs in obs["filings"]:
        r = classify_filing(tables, fobs)
        transitions.extend(r["transitions"])
        unresolved |= r["unresolved"]
        for t in PK:
            added[t].extend(r["added"][t])
            updated[t].extend(r["updated"][t])
    transitions.sort(key=lambda t: (t["filing_id"], t["transition"],
                                    str(sorted(t.items()))))
    return {"transitions": transitions, "added": added,
            "updated": updated, "unresolved": unresolved}
