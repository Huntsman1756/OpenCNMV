"""Cross-variant fact comparison — G1-B/G1-C semantics promoted to the
durable read surface.

Verbatim rules (evidence: g1/G1-B-dual-language-capture/g1b_compare.py,
g1/G1-C-extension-variant-identity/g1c_compare_mapped.py):

  * cross_variant_key = concept | entity | period | unit | dims
    (xml:lang dropped so the same economic fact pairs across -es/-en).
  * Only PROVEN_EQUIVALENT extension_mapping pairs rewrite identity:
    concept, dimension axis and explicit member qnames become pair_id.
    AMBIGUOUS / CONFLICT / UNMATCHED never merge.
  * Multiset pairing per key: each side sorted by value_sha256, zipped;
    residue -> VARIANT_ONLY_FACT. Never a cross-product, never a dedup.
  * Language-sensitive concept types are never economic divergences.
  * Payload: identical value_sha256 + decimals -> MATCH_EXACT;
    Decimal-equal numerics -> MATCH_NUMERIC_EQUIVALENT; otherwise
    DIVERGENT_SUBMISSION_FACT.
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from opencnmv.query.dataset import Dataset, resolve_filing_id

TEXT_TYPE_LOCALNAMES = {
    "stringItemType", "normalizedStringItemType", "tokenItemType",
    "langItemType", "textBlockItemType",
}

CLASSES = ("MATCH_EXACT", "MATCH_NUMERIC_EQUIVALENT",
           "DIVERGENT_SUBMISSION_FACT", "VARIANT_ONLY_FACT",
           "LANGUAGE_SENSITIVE_NOT_COMPARED", "UNMAPPED_VARIANT_FACT")


def _period_of(r: dict) -> str:
    if r.get("period_forever"):
        return "forever"
    if r.get("period_instant"):
        return r["period_instant"]
    return f"{r.get('period_start') or ''}/{r.get('period_end') or ''}"


def _ns(qname: str) -> str:
    return qname.rsplit("#", 1)[0]


def _is_lang_sensitive(r: dict) -> bool:
    ct = (r.get("concept_type") or "").rsplit("#", 1)[-1] \
        .rsplit("/", 1)[-1]
    return ct in TEXT_TYPE_LOCALNAMES


def _dec(v: str | None) -> Decimal | None:
    try:
        return Decimal((v or "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _rec(row: dict) -> dict:
    """A facts-table row as a comparison record."""
    return {
        "concept": row["concept"],
        "entity_scheme": row["entity_scheme"],
        "entity": row["entity"],
        "period": _period_of(row),
        "unit": row["unit"],
        "dims": json.loads(row["canonical_dims_json"] or "{}"),
        "lang": row["lang"],
        "value_sha256": row["value_sha256"],
        "decimals": row["decimals"],
        "isNil": row["isNil"],
        "is_numeric": row["is_numeric"],
        "concept_type": row["concept_type"],
        "value": (row["value_full"] if row["value_full"] is not None
                  else row["value_preview"]),
        "xValue": (row["xValue_full"] if row["xValue_full"] is not None
                   else row["xValue_preview"]),
        "fact_id": row["fact_id"],
        "seq": row["seq"],
        "ns_kind": row["ns_kind"],
        "mapped": {},
    }


def _rewrite(rec: dict, pairs: dict[str, str]) -> dict:
    """PROVEN_EQUIVALENT rewrite: concept / dim axis / E:member -> pair_id.
    Non-proven qnames keep their native form (they cannot pair)."""
    rec = dict(rec)
    rec["dims"] = dict(rec["dims"])
    rec["mapped"] = {}
    if rec["concept"] in pairs:
        rec["mapped"]["concept"] = pairs[rec["concept"]]
        rec["concept"] = pairs[rec["concept"]]
    nd = {}
    for k, v in rec["dims"].items():
        nk = pairs.get(k, k)
        nv = v
        if v.startswith("E:") and v[2:] in pairs:
            nv = "E:" + pairs[v[2:]]
        if nk != k or nv != v:
            rec["mapped"].setdefault("dimensions", {})[k] = (nk, nv)
        nd[nk] = nv
    rec["dims"] = nd
    return rec


def _cv_key(r: dict) -> str:
    """Cross-variant key: native identity minus xml:lang."""
    return "|".join([
        r["concept"], r.get("entity_scheme") or "", r.get("entity") or "",
        r["period"], r.get("unit") or "",
        ";".join(f"{k}={v}" for k, v in sorted(r["dims"].items()))])


def _native_key(r: dict) -> str:
    return _cv_key(r) + "|" + (r.get("lang") or "")


def _payload(r: dict) -> dict:
    return {"value": r["value"], "value_sha256": r["value_sha256"],
            "xValue": r["xValue"], "decimals": r["decimals"],
            "isNil": r["isNil"], "lang": r["lang"],
            "fact_id": r["fact_id"],
            "native_fact_key": _native_key(r)}


def _key_brief(r: dict) -> dict:
    return {"concept": r["concept"],
            "entity": f"{r.get('entity_scheme') or ''}"
                      f"|{r.get('entity') or ''}",
            "period": r["period"], "unit": r.get("unit") or "",
            "dimensions": r["dims"],
            "concept_type": r.get("concept_type")}


def _classify_pair(a: dict, b: dict) -> str:
    if a["isNil"] or b["isNil"]:
        return ("MATCH_EXACT" if a["isNil"] and b["isNil"]
                else "DIVERGENT_SUBMISSION_FACT")
    if a["value_sha256"] == b["value_sha256"] \
            and a["decimals"] == b["decimals"]:
        return "MATCH_EXACT"
    if a.get("is_numeric") and b.get("is_numeric"):
        da, db = _dec(a["value"]), _dec(b["value"])
        if da is not None and db is not None:
            return ("MATCH_NUMERIC_EQUIVALENT" if da == db
                    else "DIVERGENT_SUBMISSION_FACT")
    return "DIVERGENT_SUBMISSION_FACT"


def compare_variants(left_recs: list[dict], right_recs: list[dict],
                     ext_left: set[str], ext_right: set[str],
                     pairs: dict[str, str],
                     left: str = "es", right: str = "en") -> dict:
    """Pure comparison of two rewritten fact-record lists.

    Returns {"counts", "match_exact_count", "records"} — records carry
    every non-MATCH_EXACT classification deterministically ordered.
    Payload fields are keyed by the actual side languages.
    """
    es = [_rewrite(r, pairs) for r in left_recs]
    en = [_rewrite(r, pairs) for r in right_recs]
    ext_union = ext_left | ext_right

    counts: dict[str, int] = {c: 0 for c in CLASSES}
    records: list[dict] = []
    match_exact_keys: list[str] = []

    def variant_only(side, r, note=None):
        counts["VARIANT_ONLY_FACT"] += 1
        ext_dim = any(v.startswith("E:")
                      and v[2:].rsplit("#", 1)[0] in ext_union
                      for v in r["dims"].values())
        rec = {"class": "VARIANT_ONLY_FACT", "variant": side,
               "key": _key_brief(r), "payload": _payload(r),
               "extension_dim_member": ext_dim}
        if note:
            rec["note"] = note
        records.append(rec)

    # extension-namespace facts that stayed unmapped after the PROVEN
    # rewrite: cross-variant identity is not justifiable
    es_map: dict[str, list[dict]] = defaultdict(list)
    en_map: dict[str, list[dict]] = defaultdict(list)
    for r in es:
        es_map[_cv_key(r)].append(r)
    for r in en:
        en_map[_cv_key(r)].append(r)
    en_concepts = {r["concept"] for r in en}
    es_concepts = {r["concept"] for r in es}

    for side, recs, ext, other_concepts, other_map in (
            (left, es, ext_left, en_concepts, en_map),
            (right, en, ext_right, es_concepts, es_map)):
        for r in recs:
            if _ns(r["concept"]) in ext:
                counts["UNMAPPED_VARIANT_FACT"] += 1
                ck = _cv_key(r)
                rec = {"class": "UNMAPPED_VARIANT_FACT",
                       "variant": side, "key": _key_brief(r),
                       "payload": _payload(r),
                       "qname_in_both_variants":
                           r["concept"] in other_concepts}
                if other_map.get(ck):
                    o = other_map[ck][0]
                    rec["shadow_payload_equal"] = (
                        o["value_sha256"] == r["value_sha256"]
                        and o["decimals"] == r["decimals"]
                        and o["isNil"] == r["isNil"])
                records.append(rec)

    es_cmp = defaultdict(list)
    en_cmp = defaultdict(list)
    for k, lst in es_map.items():
        for r in lst:
            if _ns(r["concept"]) not in ext_left:
                es_cmp[k].append(r)
    for k, lst in en_map.items():
        for r in lst:
            if _ns(r["concept"]) not in ext_right:
                en_cmp[k].append(r)

    for k in sorted(set(es_cmp) | set(en_cmp)):
        es_l, en_l = es_cmp.get(k, []), en_cmp.get(k, [])
        probe = (es_l or en_l)[0]
        if _is_lang_sensitive(probe):
            if es_l and en_l:
                counts["LANGUAGE_SENSITIVE_NOT_COMPARED"] += \
                    min(len(es_l), len(en_l))
                records.append({
                    "class": "LANGUAGE_SENSITIVE_NOT_COMPARED",
                    "key": _key_brief(probe),
                    f"{left}_lang": es_l[0].get("lang"),
                    f"{right}_lang": en_l[0].get("lang"),
                    "multiplicity": {left: len(es_l),
                                     right: len(en_l)}})
                for extra, side in ((es_l[len(en_l):], left),
                                    (en_l[len(es_l):], right)):
                    for r in extra:
                        variant_only(side, r, "multiplicity asymmetry")
            else:
                side = left if es_l else right
                for r in (es_l or en_l):
                    variant_only(side, r)
            continue
        es_s = sorted(es_l, key=lambda r: (r.get("value_sha256") or ""))
        en_s = sorted(en_l, key=lambda r: (r.get("value_sha256") or ""))
        for a, b in zip(es_s, en_s):
            cls = _classify_pair(a, b)
            counts[cls] += 1
            if cls == "MATCH_EXACT":
                match_exact_keys.append(k)
            else:
                rec = {"class": cls, "key": _key_brief(a),
                       left: _payload(a), right: _payload(b)}
                for tag, r_ in ((left, a), (right, b)):
                    if r_.get("mapped"):
                        m = rec.get("mapped")
                        if not isinstance(m, dict):
                            m = {}
                            rec["mapped"] = m
                        m[tag] = r_["mapped"]
                records.append(rec)
        for extra, side in ((es_s[len(en_s):], left),
                            (en_s[len(es_s):], right)):
            for r in extra:
                variant_only(side, r, "no counterpart under "
                                      "cross_variant_key")
    return {"counts": counts,
            "match_exact_count": len(match_exact_keys),
            "records": records}


def _latest_observed_vv(ds: Dataset, variant_id: str) -> dict | None:
    rows = ds.sql(
        "SELECT * FROM variant_version WHERE variant_id = ? "
        "AND observed ORDER BY version_seq DESC LIMIT 1", [variant_id])
    return rows[0] if rows else None


def compare_filing(ds: Dataset, ref: str) -> dict:
    """Semantic cross-variant comparison for one filing.

    Compares the latest *observed* variant_version of each submission
    variant. Single-variant filings report SKIPPED_SINGLE_VARIANT with
    the view-resolution evidence (a UI fallback is not a variant).
    """
    fid = resolve_filing_id(ds, ref)
    variants = ds.sql(
        "SELECT * FROM submission_variant WHERE filing_id = ? "
        "ORDER BY variant_ordinal", [fid])
    vrs = ds.sql("SELECT requested_ui_language, resolved_variant_id, "
                 "resolution_mode FROM view_resolution "
                 "WHERE filing_id = ? ORDER BY ordinal", [fid])
    if len(variants) < 2:
        return {"filing_id": fid, "status": "SKIPPED_SINGLE_VARIANT",
                "submitted_variants": [v["variant_id"] for v in variants],
                "view_resolutions": vrs,
                "note": "a UI-language fallback is not a submitted "
                        "variant; nothing to compare"}

    sides: dict[str, dict] = {}
    for v in variants:  # variant_ordinal order — deterministic sides
        vv = _latest_observed_vv(ds, v["variant_id"])
        sides[v["submission_language"]] = {
            "variant_id": v["variant_id"],
            "variant_version_id":
                vv["variant_version_id"] if vv else None,
            "facts": [] if vv is None else ds.sql(
                "SELECT * FROM facts WHERE variant_version_id = ? "
                "ORDER BY seq", [vv["variant_version_id"]])}

    a_lang, b_lang = list(sides)[:2]
    a_rows, b_rows = sides[a_lang]["facts"], sides[b_lang]["facts"]
    ext = {
        lg: {_ns(r["concept"]) for r in sides[lg]["facts"]
             if r["ns_kind"] == "issuer_extension"}
        for lg in (a_lang, b_lang)}

    pair_rows = ds.sql(
        "SELECT source_qname, target_qname, pair_id FROM "
        "extension_mapping WHERE filing_id = ? AND "
        "verdict = 'PROVEN_EQUIVALENT'", [fid])
    pairs: dict[str, str] = {}
    for p in pair_rows:
        pairs[p["source_qname"]] = p["pair_id"]
        pairs[p["target_qname"]] = p["pair_id"]

    rep = compare_variants(
        [_rec(r) for r in a_rows], [_rec(r) for r in b_rows],
        ext[a_lang], ext[b_lang], pairs, left=a_lang, right=b_lang)
    return {"filing_id": fid, "status": "COMPARED",
            "compared": {
                a_lang: {"variant_id": sides[a_lang]["variant_id"],
                         "variant_version_id":
                             sides[a_lang]["variant_version_id"],
                         "facts": len(a_rows)},
                b_lang: {"variant_id": sides[b_lang]["variant_id"],
                         "variant_version_id":
                             sides[b_lang]["variant_version_id"],
                         "facts": len(b_rows)}},
            "proven_pairs_applied": len(pair_rows),
            "counts": rep["counts"],
            "match_exact_count": rep["match_exact_count"],
            "records": rep["records"]}
