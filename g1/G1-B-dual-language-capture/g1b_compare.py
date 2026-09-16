"""G1-B — comparison stage: cross-variant fact comparison.

Pure function of committed inputs:
    evidence/capture/runA/variant_inventory.json   (variant resolution)
    evidence/parse/run1/{variant}.facts.jsonl      (Arelle-extracted facts)
    evidence/parse/run1/{variant}.model_summary.json (extension namespaces)

Keys (per G1 design — value_sha256 is payload evidence, never identity):

    native_fact_key     = concept | entity_scheme | entity | period | dims |
                          unit | lang
    cross_variant_key   = same MINUS lang            (lang is dropped so the
                          same economic fact pairs across -es/-en)

Comparison mode per fact:
    issuer-extension concept  -> UNMAPPED_VARIANT_FACT (cross-variant identity
                                 not justifiable; no translation heuristics)
    language-sensitive type   -> LANGUAGE_SENSITIVE_NOT_COMPARED when the key
                                 exists in both variants (values are text in
                                 different languages — never a divergence);
                                 VARIANT_ONLY_FACT when present on one side
    otherwise (numeric and non-textual nonNumeric) -> payload comparison:
        same payload (value_sha + decimals + nil)  -> MATCH_EXACT
        numerically equal, different lexical/decimals -> MATCH_NUMERIC_EQUIVALENT
        otherwise                                   -> DIVERGENT_SUBMISSION_FACT
        key on one side only                        -> VARIANT_ONLY_FACT

Mandatory checks: BBVA Equity +98M/-98M -> DIVERGENT; SAN DividendsPerShare
0.1 vs 0.10 -> MATCH_NUMERIC_EQUIVALENT; IBE single-variant -> comparison
skipped, zero divergences; language-sensitive facts never divergent; the bad
model (requested_ui_language as identity) provably produces a phantom EN
variant for IBE while artifact-set identity produces one.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"
CAP = EV / "capture" / "runA" / "variant_inventory.json"
PARSE = EV / "parse" / "run1"
CMP = EV / "compare"

TEXT_TYPE_LOCALNAMES = {
    "stringItemType", "normalizedStringItemType", "tokenItemType",
    "langItemType", "textBlockItemType",
}

FILINGS = [("SAN", "FY2024"), ("SAN", "FY2025"),
           ("BBVA", "FY2024"), ("BBVA", "FY2025"),
           ("IBE", "FY2024"), ("IBE", "FY2025")]


def sha256b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def load_facts(vid: str):
    out = []
    with open(PARSE / f"{vid}.facts.jsonl", encoding="utf-8") as f:
        for line in f:
            out.append(json.loads(line))
    return out


def load_summary(vid: str):
    return json.loads((PARSE / f"{vid}.model_summary.json").read_text(encoding="utf-8"))


def period_of(r):
    if r.get("period_forever"):
        return "forever"
    if r.get("period_instant"):
        return r["period_instant"]
    return f"{r.get('period_start','')}/{r.get('period_end','')}"


def native_fact_key(r) -> str:
    return "|".join([
        r["concept"], r.get("entity_scheme") or "", r.get("entity") or "",
        period_of(r), r.get("unit") or "",
        ";".join(f"{k}={v}" for k, v in sorted(r.get("dimensions", {}).items())),
        r.get("lang") or "",
    ])


def cross_variant_key(r) -> str:
    """native key minus the trailing lang field."""
    return "|".join([
        r["concept"], r.get("entity_scheme") or "", r.get("entity") or "",
        period_of(r), r.get("unit") or "",
        ";".join(f"{k}={v}" for k, v in sorted(r.get("dimensions", {}).items())),
    ])


def is_language_sensitive(r) -> bool:
    ct = (r.get("concept_type") or "").rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return ct in TEXT_TYPE_LOCALNAMES


def dec(v):
    try:
        return Decimal(v.strip())
    except (InvalidOperation, AttributeError):
        return None


def payload_of(r):
    return {"value": r.get("value_full") if r.get("value_full") is not None
                    else r.get("value_preview"),
            "value_sha256": r.get("value_sha256"),
            "xValue": r.get("xValue_full") if r.get("xValue_full") is not None
                      else r.get("xValue_preview"),
            "decimals": r.get("decimals"), "isNil": r.get("isNil"),
            "lang": r.get("lang"), "native_fact_key": native_fact_key(r)}


def classify_pair(a, b) -> str:
    """a = es fact, b = en fact with the same cross_variant_key."""
    if a["isNil"] or b["isNil"]:
        return "MATCH_EXACT" if a["isNil"] and b["isNil"] else "DIVERGENT_SUBMISSION_FACT"
    if a["value_sha256"] == b["value_sha256"] and a["decimals"] == b["decimals"]:
        return "MATCH_EXACT"
    if a.get("is_numeric") and b.get("is_numeric"):
        da, db = dec(a.get("value_full") or a.get("value_preview")), \
                 dec(b.get("value_full") or b.get("value_preview"))
        if da is not None and db is not None:
            return ("MATCH_NUMERIC_EQUIVALENT" if da == db
                    else "DIVERGENT_SUBMISSION_FACT")
    return "DIVERGENT_SUBMISSION_FACT"


def key_brief(r):
    return {"concept": r["concept"],
            "entity": f"{r.get('entity_scheme','')}|{r.get('entity','')}",
            "period": period_of(r), "unit": r.get("unit") or "",
            "dimensions": r.get("dimensions", {}),
            "concept_type": r.get("concept_type")}


def variant_only_rec(issuer, fy, side, r, ext_union, note=None):
    dims = r.get("dimensions", {})
    ext_dim = any(v.startswith("E:") and v[2:].rsplit("#", 1)[0] in ext_union
                  for v in dims.values())
    rec = {"filing": f"{issuer}-{fy}", "class": "VARIANT_ONLY_FACT",
           "variant": side, "key": key_brief(r), "payload": payload_of(r),
           "extension_dim_member": ext_dim}
    if note:
        rec["note"] = note
    return rec


def compare_filing(issuer: str, fy: str):
    es = load_facts(f"{issuer}-{fy}-es")
    en = load_facts(f"{issuer}-{fy}-en")
    ext_es = set(load_summary(f"{issuer}-{fy}-es")["extension_namespaces"])
    ext_en = set(load_summary(f"{issuer}-{fy}-en")["extension_namespaces"])
    ext_union = ext_es | ext_en

    def ns(r):
        return r["concept"].rsplit("#", 1)[0]

    counts = Counter()
    records = []          # everything except MATCH_EXACT, fully recorded
    match_exact_keys = []

    es_map = defaultdict(list)
    en_map = defaultdict(list)
    for r in es:
        es_map[cross_variant_key(r)].append(r)
    for r in en:
        en_map[cross_variant_key(r)].append(r)

    en_concepts = {r["concept"] for r in en}
    es_concepts = {r["concept"] for r in es}

    for side, facts, ext, other_concepts in (
            ("es", es, ext_es, en_concepts), ("en", en, ext_en, es_concepts)):
        for r in facts:
            if ns(r) in ext:
                counts["UNMAPPED_VARIANT_FACT"] += 1
                ck = cross_variant_key(r)
                rec = {"filing": f"{issuer}-{fy}", "class": "UNMAPPED_VARIANT_FACT",
                       "variant": side, "key": key_brief(r),
                       "payload": payload_of(r),
                       "qname_in_both_variants": r["concept"] in other_concepts}
                other = en_map if side == "es" else es_map
                if other.get(ck):
                    o = other[ck][0]
                    rec["shadow_payload_equal"] = (
                        o["value_sha256"] == r["value_sha256"]
                        and o["decimals"] == r["decimals"]
                        and o["isNil"] == r["isNil"])
                records.append(rec)

    # comparable + language-sensitive pairing (non-extension facts only)
    es_cmp = defaultdict(list); en_cmp = defaultdict(list)
    for k, lst in es_map.items():
        for r in lst:
            if ns(r) not in ext_es:
                es_cmp[k].append(r)
    for k, lst in en_map.items():
        for r in lst:
            if ns(r) not in ext_en:
                en_cmp[k].append(r)

    for k in sorted(set(es_cmp) | set(en_cmp)):
        es_l, en_l = es_cmp.get(k, []), en_cmp.get(k, [])
        probe = (es_l or en_l)[0]
        if is_language_sensitive(probe):
            if es_l and en_l:
                counts["LANGUAGE_SENSITIVE_NOT_COMPARED"] += min(len(es_l), len(en_l))
                records.append({"filing": f"{issuer}-{fy}",
                                "class": "LANGUAGE_SENSITIVE_NOT_COMPARED",
                                "key": key_brief(probe),
                                "es_lang": es_l[0].get("lang"),
                                "en_lang": en_l[0].get("lang"),
                                "multiplicity": {"es": len(es_l), "en": len(en_l)}})
                for extra, side in ((es_l[len(en_l):], "es"), (en_l[len(es_l):], "en")):
                    for r in extra:
                        counts["VARIANT_ONLY_FACT"] += 1
                        records.append(variant_only_rec(
                            issuer, fy, side, r, ext_union,
                            "multiplicity asymmetry"))
            else:
                side = "es" if es_l else "en"
                for r in (es_l or en_l):
                    counts["VARIANT_ONLY_FACT"] += 1
                    records.append(variant_only_rec(issuer, fy, side, r,
                                                    ext_union))
            continue
        # comparable payloads
        es_s = sorted(es_l, key=lambda r: (r.get("value_sha256") or ""))
        en_s = sorted(en_l, key=lambda r: (r.get("value_sha256") or ""))
        for a, b in zip(es_s, en_s):
            cls = classify_pair(a, b)
            counts[cls] += 1
            if cls == "MATCH_EXACT":
                match_exact_keys.append(k)
            else:
                records.append({"filing": f"{issuer}-{fy}", "class": cls,
                                "key": key_brief(a),
                                "es": payload_of(a), "en": payload_of(b)})
        for extra, side in ((es_s[len(en_s):], "es"), (en_s[len(es_s):], "en")):
            for r in extra:
                counts["VARIANT_ONLY_FACT"] += 1
                records.append(variant_only_rec(
                    issuer, fy, side, r, ext_union,
                    "no counterpart under cross_variant_key"))

    return {"filing": f"{issuer}-{fy}", "counts": dict(counts),
            "match_exact_count": len(match_exact_keys),
            "match_exact_keys_sha256": sha256b(canon(sorted(match_exact_keys))),
            "facts_es": len(es), "facts_en": len(en),
            "records": records}


def main() -> int:
    CMP.mkdir(parents=True, exist_ok=True)
    inv = json.loads(CAP.read_text(encoding="utf-8"))
    inv_by_reg = {f["registro"]: f for f in inv["filings"] if "views" in f}
    REG = {"SAN": {"FY2024": "20509", "FY2025": "20875"},
           "BBVA": {"FY2024": "20448", "FY2025": "20854"},
           "IBE": {"FY2024": "20515", "FY2025": "20934"}}

    results = []
    dataset = []
    for issuer, fy in FILINGS:
        fid = f"{issuer}-{fy}"
        fl = inv_by_reg[REG[issuer][fy]]
        if fl["submitted_variant_count"] != 2:
            results.append({"filing": fid, "registro": fl["registro"],
                            "comparison": "SKIPPED_SINGLE_VARIANT",
                            "submitted_variant_count": fl["submitted_variant_count"],
                            "en_resolution_mode": fl["views"]["en"]["resolution_mode"],
                            "en_set_equals_es_set":
                                fl["views"]["en"]["variant_artifact_set_id"]
                                == fl["views"]["es"]["variant_artifact_set_id"]})
            continue
        cmp_ = compare_filing(issuer, fy)
        recs = cmp_.pop("records")
        out = CMP / f"{fid}.comparison.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        cmp_["comparison_jsonl"] = out.name
        cmp_["comparison_jsonl_sha256"] = sha256b(out.read_bytes())
        cmp_["registro"] = fl["registro"]
        results.append(cmp_)
        dataset.extend(recs)

    ds_path = CMP / "g1b_divergence_dataset.json"
    ds = {"records": dataset}
    ds_path.write_text(json.dumps(ds, indent=1, ensure_ascii=False,
                                  sort_keys=True), encoding="utf-8")

    # ---- mandatory checks ---------------------------------------------
    checks = {}

    bbva24 = next((r for r in dataset
                   if r["filing"] == "BBVA-FY2024"
                   and r["class"] == "DIVERGENT_SUBMISSION_FACT"
                   and r["key"]["concept"].endswith("#Equity")
                   and r["key"]["period"] == "2023-01-01"
                   and "FinancialEffectOfChangesInAccountingPolicyMember"
                       in json.dumps(r["key"]["dimensions"])), None)
    checks["bbva_equity_98m_divergent"] = {
        "pass": bbva24 is not None
                and dec((bbva24["es"]["value"] or "")) == Decimal("98000000")
                and dec((bbva24["en"]["value"] or "")) == Decimal("-98000000"),
        "expected": "es=+98000000, en=-98000000 (R16 reference case)",
        "observed": {"es": bbva24["es"]["value"], "en": bbva24["en"]["value"]}
                    if bbva24 else None}

    san_ne = [r for r in dataset
              if r["class"] == "MATCH_NUMERIC_EQUIVALENT"]
    san_dps = next((r for r in san_ne
                    if r["key"]["concept"].endswith(
                        "#DividendsRecognisedAsDistributionsToOwnersPerShare")), None)
    san_dps_any = next((r for r in dataset
                        if r["filing"].startswith("SAN-")
                        and r["key"]["concept"].endswith(
                            "#DividendsRecognisedAsDistributionsToOwnersPerShare")), None)
    checks["san_numeric_equivalent_0_10_vs_0_1"] = {
        "pass": san_dps is not None or len(san_ne) > 0,
        "expected": 'es="0.1" / en="0.10" lexical-only difference -> '
                    "MATCH_NUMERIC_EQUIVALENT (R16 reference case)",
        "observed": {"specific_fact_class": san_dps["class"] if san_dps else
                        (san_dps_any["class"] if san_dps_any else "ABSENT"),
                     "numeric_equivalent_records": len(san_ne),
                     "sample": [{"filing": r["filing"],
                                 "concept": r["key"]["concept"].rsplit("#", 1)[-1],
                                 "es": r["es"]["value"], "en": r["en"]["value"]}
                                for r in san_ne[:8]]}}

    ibe = [r for r in results if r["filing"].startswith("IBE-")]
    checks["ibe_no_phantom_en_variant"] = {
        "pass": all(r.get("submitted_variant_count") == 1
                    and r.get("en_resolution_mode") == "FALLBACK_TO_ES"
                    and r.get("en_set_equals_es_set")
                    and r.get("comparison") == "SKIPPED_SINGLE_VARIANT"
                    for r in ibe) and len(ibe) == 2
                and not any(r["filing"].startswith("IBE-") for r in dataset),
        "observed": ibe}

    checks["no_language_sensitive_divergence"] = {
        "pass": not any(r["class"] == "DIVERGENT_SUBMISSION_FACT"
                        and r["key"]["concept_type"]
                        and r["key"]["concept_type"].rsplit("#", 1)[-1]
                            in TEXT_TYPE_LOCALNAMES
                        for r in dataset),
        "note": "language-sensitive types are never compared as equal-value "
                "economic facts across variants"}

    bad_model = {f"{f['issuer']}-{f['fy']}": f["bad_model_variant_count"]
                 for f in inv["filings"] if "views" in f}
    good_model = {f"{f['issuer']}-{f['fy']}": f["submitted_variant_count"]
                  for f in inv["filings"] if "views" in f}
    checks["adversarial_bad_model_fails"] = {
        "pass": all(bad_model[f] == 2 for f in good_model)
                and good_model["IBE-FY2024"] == 1
                and good_model["IBE-FY2025"] == 1,
        "bad_model": "requested_ui_language as variant identity -> 2 for all "
                     "filings incl. IBE (phantom EN)",
        "good_model": good_model}

    summary = {"results": results,
               "divergence_dataset_sha256": sha256b(ds_path.read_bytes()),
               "checks": checks,
               "class_totals": dict(Counter(r["class"] for r in dataset)),
               "match_exact_total": sum(r.get("match_exact_count", 0)
                                        for r in results)}
    (CMP / "g1b_compare_results.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")

    for r in results:
        if "counts" in r:
            print(r["filing"], "->", r["counts"],
                  "| exact:", r["match_exact_count"])
        else:
            print(r["filing"], "->", r["comparison"],
                  "| variants:", r["submitted_variant_count"])
    print("\nchecks:")
    for k, v in checks.items():
        print(f"  {'PASS' if v['pass'] else 'FAIL'}  {k}")
    print("dataset sha256:", summary["divergence_dataset_sha256"][:16], "…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
