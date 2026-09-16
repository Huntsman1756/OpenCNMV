# G1-C — mapped re-comparison: re-runs the G1-B cross-variant comparison on
# the SAME fact bytes, but with PROVEN_EQUIVALENT extension pairs rewritten to
# a canonical pair id inside the fact key:
#
#     concept  ext qname -> PAIR::<sorted es/en qnames>   (only if PROVEN)
#     dim axis ext qname -> PAIR::...                     (only if PROVEN)
#     dim member E:ext   -> E:PAIR::...                   (only if PROVEN)
#
# Everything unmapped/ambiguous/conflict keeps its native qname and therefore
# still cannot pair across variants -> remains UNMAPPED/VARIANT_ONLY. The G1-B
# baseline dataset is NOT modified; this stage produces a separate mapped
# dataset plus the delta metrics the gate exists for:
#
#     previously UNMAPPED_VARIANT_FACT / VARIANT_ONLY_FACT
#        -> now pairable -> MATCH_* / DIVERGENT_SUBMISSION_FACT
#
# Reuses g1b_compare helpers verbatim (same classification semantics).
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "g1/G1-B-dual-language-capture"))
import g1b_compare as B  # noqa: E402

EV = HERE / "evidence"
STR = EV / "structure"
MAP = EV / "mapping"
OUT = EV / "compare_mapped"

DUAL = [("SAN", "FY2024"), ("SAN", "FY2025"),
        ("BBVA", "FY2024"), ("BBVA", "FY2025")]


def load_pairs(fid):
    doc = json.loads((MAP / f"{fid}.mapping.json").read_text(encoding="utf-8"))
    pairs = {}
    for r in doc["records"]:
        if r["verdict"] == "PROVEN_EQUIVALENT":
            pairs[r["source_qname"]] = r["pair_id"]
            pairs[r["target_qname"]] = r["pair_id"]
    return pairs


def rewrite_fact(r, pairs):
    r = dict(r)
    mapped = {}
    if r["concept"] in pairs:
        mapped["concept"] = pairs[r["concept"]]
        r["concept"] = pairs[r["concept"]]
    dims = r.get("dimensions") or {}
    if dims:
        nd = {}
        for k, v in dims.items():
            nk = pairs.get(k, k)
            nv = v
            if v.startswith("E:") and v[2:] in pairs:
                nv = "E:" + pairs[v[2:]]
            if nk != k or nv != v:
                mapped.setdefault("dimensions", {})[k] = (nk, nv)
            nd[nk] = nv
        r["dimensions"] = nd
    if mapped:
        r["mapped"] = mapped
    return r


def compare_filing_mapped(issuer, fy):
    fid = f"{issuer}-{fy}"
    pairs = load_pairs(fid)
    es = [rewrite_fact(r, pairs) for r in B.load_facts(f"{fid}-es")]
    en = [rewrite_fact(r, pairs) for r in B.load_facts(f"{fid}-en")]
    ext_es = set(B.load_summary(f"{fid}-es")["extension_namespaces"])
    ext_en = set(B.load_summary(f"{fid}-en")["extension_namespaces"])
    ext_union = ext_es | ext_en

    def ns(r):
        return r["concept"].rsplit("#", 1)[0]

    counts = Counter()
    records, match_exact_keys = [], []
    es_map = defaultdict(list)
    en_map = defaultdict(list)
    for r in es:
        es_map[B.cross_variant_key(r)].append(r)
    for r in en:
        en_map[B.cross_variant_key(r)].append(r)

    for side, facts, ext in (("es", es, ext_es), ("en", en, ext_en)):
        for r in facts:
            if ns(r) in ext:
                counts["UNMAPPED_VARIANT_FACT"] += 1
                records.append({"filing": fid, "class": "UNMAPPED_VARIANT_FACT",
                                "variant": side, "key": B.key_brief(r),
                                "payload": B.payload_of(r)})

    es_cmp = defaultdict(list)
    en_cmp = defaultdict(list)
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
        if B.is_language_sensitive(probe):
            if es_l and en_l:
                counts["LANGUAGE_SENSITIVE_NOT_COMPARED"] += min(len(es_l),
                                                               len(en_l))
                records.append({"filing": fid,
                                "class": "LANGUAGE_SENSITIVE_NOT_COMPARED",
                                "key": B.key_brief(probe),
                                "es_lang": es_l[0].get("lang"),
                                "en_lang": en_l[0].get("lang"),
                                "multiplicity": {"es": len(es_l),
                                                 "en": len(en_l)}})
                for extra, side in ((es_l[len(en_l):], "es"),
                                    (en_l[len(es_l):], "en")):
                    for r in extra:
                        counts["VARIANT_ONLY_FACT"] += 1
                        records.append(B.variant_only_rec(
                            issuer, fy, side, r, ext_union,
                            "multiplicity asymmetry"))
            else:
                side = "es" if es_l else "en"
                for r in (es_l or en_l):
                    counts["VARIANT_ONLY_FACT"] += 1
                    records.append(B.variant_only_rec(issuer, fy, side, r,
                                                      ext_union))
            continue
        es_s = sorted(es_l, key=lambda r: (r.get("value_sha256") or ""))
        en_s = sorted(en_l, key=lambda r: (r.get("value_sha256") or ""))
        for a, b in zip(es_s, en_s):
            cls = B.classify_pair(a, b)
            counts[cls] += 1
            if cls == "MATCH_EXACT":
                match_exact_keys.append(k)
            else:
                rec = {"filing": fid, "class": cls, "key": B.key_brief(a),
                       "es": B.payload_of(a), "en": B.payload_of(b)}
                for tag, r_ in (("es", a), ("en", b)):
                    if r_.get("mapped"):
                        rec.setdefault("mapped", {})[tag] = r_["mapped"]
                records.append(rec)
        for extra, side in ((es_s[len(en_s):], "es"),
                            (en_s[len(es_s):], "en")):
            for r in extra:
                counts["VARIANT_ONLY_FACT"] += 1
                records.append(B.variant_only_rec(
                    issuer, fy, side, r, ext_union,
                    "no counterpart under mapped cross_variant_key"))

    return {"filing": fid, "counts": dict(counts),
            "match_exact_count": len(match_exact_keys),
            "match_exact_keys_sha256": B.sha256b(B.canon(sorted(match_exact_keys))),
            "proven_pairs_applied": len(pairs) // 2,
            "facts_es": len(es), "facts_en": len(en),
            "records": records}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = json.loads((B.CMP / "g1b_compare_results.json")
                      .read_text(encoding="utf-8"))
    base_by_filing = {r["filing"]: r for r in base["results"]
                      if "counts" in r}

    results, dataset = [], []
    for issuer, fy in DUAL:
        cmp_ = compare_filing_mapped(issuer, fy)
        recs = cmp_.pop("records")
        out = OUT / f"{issuer}-{fy}.comparison.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        cmp_["comparison_jsonl_sha256"] = B.sha256b(out.read_bytes())
        b = base_by_filing[f"{issuer}-{fy}"]
        delta = {}
        for cls in set(b["counts"]) | set(cmp_["counts"]) | {"MATCH_EXACT"}:
            bv = b["counts"].get(cls, b.get("match_exact_count", 0)
                                 if cls == "MATCH_EXACT" else 0)
            mv = cmp_["counts"].get(cls, cmp_["match_exact_count"]
                                    if cls == "MATCH_EXACT" else 0)
            if bv != mv:
                delta[cls] = {"baseline": bv, "mapped": mv}
        cmp_["delta_vs_g1b"] = delta
        results.append(cmp_)
        dataset.extend(recs)
        print(cmp_["filing"], "->", cmp_["counts"],
              "| exact:", cmp_["match_exact_count"],
              "| pairs:", cmp_["proven_pairs_applied"], flush=True)

    ds_path = OUT / "g1c_mapped_dataset.json"
    ds_path.write_text(json.dumps({"records": dataset}, indent=1,
                                  ensure_ascii=False, sort_keys=True),
                       encoding="utf-8")

    new_divergent = [r for r in dataset
                     if r["class"] == "DIVERGENT_SUBMISSION_FACT"]
    summary = {
        "results": results,
        "mapped_dataset_sha256": B.sha256b(ds_path.read_bytes()),
        "class_totals": dict(Counter(r["class"] for r in dataset)),
        "match_exact_total": sum(r["match_exact_count"] for r in results),
        "divergent_records": len(new_divergent),
        "baseline_divergent": base["class_totals"].get(
            "DIVERGENT_SUBMISSION_FACT", 0),
    }
    (OUT / "g1c_mapped_results.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    print("\nclass_totals:", summary["class_totals"])
    print("divergent: baseline", summary["baseline_divergent"],
          "-> mapped", summary["divergent_records"])
    print("dataset sha:", summary["mapped_dataset_sha256"][:16], "…")


if __name__ == "__main__":
    main()
