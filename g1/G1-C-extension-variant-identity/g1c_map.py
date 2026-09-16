# G1-C — EXTENSION_VARIANT_IDENTITY: cross-variant mapping stage.
#
# Pure function of committed artefacts:
#     evidence/structure/{variant}.structure.json        (this gate)
#     ../G1-B-dual-language-capture/evidence/parse/run1/{variant}.facts.jsonl
#       (only to know which ext elements bear facts / are used as members)
#
# Every issuer-extension element is evaluated under each role it plays:
#     FACT_CONCEPT   (bears facts):  signature = XBRL properties
#                    (type, periodType, balance, substGroup, abstract,
#                    nillable) + anchoring set (wider-narrower, both dirs)
#                    + presentation parent signatures + calculation
#                    parent/child signatures with weights.
#     DIMENSION_MEMBER (appears in domain-member trees / used in dims):
#                    signature = per path (axes signatures, parent-chain
#                    signatures, order, usable).
#
# Referenced extension nodes (parents, chain nodes, axes) carry a
# language-invariant structural signature (anchor set + XBRL properties):
# exact when already resolved, structural otherwise. Labels are NEVER used.
#
# Final candidates per element = intersection over the roles it plays.
# Verdicts:
#     exactly one candidate, mutually unique -> PROVEN_EQUIVALENT
#     >1 candidates (or counterpart ambiguous) -> AMBIGUOUS
#     unique partial match, signature conflict -> CONFLICT
#     none                                     -> UNMATCHED
#
# Output: evidence/mapping/{issuer}-{fy}.mapping.json  (record per element)
#         evidence/mapping/mapping_results.json        (summary + checks)
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EV = HERE / "evidence"
STR = EV / "structure"
MAP = EV / "mapping"
G1B_PARSE = (REPO / "g1/G1-B-dual-language-capture/evidence/parse/run1")

DUAL = [("SAN", "FY2024"), ("SAN", "FY2025"),
        ("BBVA", "FY2024"), ("BBVA", "FY2025")]


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def sha_of(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def props_sig(e):
    return json.dumps([e.get("type"), e.get("periodType"), e.get("balance"),
                       e.get("substitutionGroup"), e.get("abstract"),
                       e.get("nillable")], sort_keys=True)


def anchor_sig(e):
    return json.dumps([sorted(e.get("anchors_to") or []),
                       sorted(e.get("anchored_from") or [])],
                      sort_keys=True)


def node_sig(q, all_ext, ext_ns):
    """Structural signature of a *referenced* node in a linkbase path."""
    if q is None:
        return ("?", "nil")
    if q.rsplit("#", 1)[0] not in ext_ns:
        return ("T", q)
    e = all_ext.get(q)
    if e is None:
        return ("X", "unseen", q.rsplit("#", 1)[-1])
    return ("X", anchor_sig(e), props_sig(e))


def pres_sig(entry, all_ext, ext_ns, ordered=False):
    sig = [(node_sig(p["parent"], all_ext, ext_ns), p["order"])
           for p in entry.get("pres_parents") or []]
    if not ordered:
        sig = [s[0] for s in sig]
    return sorted(map(repr, sig))


def calc_sig(entry, all_ext, ext_ns):
    par = sorted(repr((node_sig(p["parent"], all_ext, ext_ns), p["weight"]))
                 for p in entry.get("calc_parents") or [])
    chi = sorted(repr((node_sig(c["child"], all_ext, ext_ns), c["weight"]))
                 for c in entry.get("calc_children") or [])
    return (par, chi)


def member_sig(entry, all_ext, ext_ns, ordered=False):
    out = []
    for p in entry.get("member_paths") or []:
        d = {"axes": sorted(repr(node_sig(a, all_ext, ext_ns))
                            for a in p["axes"]),
             "chain": [repr(node_sig(n, all_ext, ext_ns))
                       for n in p["chain_up"]],
             "usable": p["usable"]}
        if ordered:
            d["order"] = p["order"]
        out.append(d)
    return canon(sorted(out, key=lambda d: canon(d).decode()))


def concept_sig(entry, all_ext, ext_ns, ordered=False):
    return (props_sig(entry), anchor_sig(entry),
            tuple(pres_sig(entry, all_ext, ext_ns, ordered)),
            repr(calc_sig(entry, all_ext, ext_ns)))


def fact_usage(vid, ext_ns):
    """ext elements bearing facts, and ext elements used as dim members."""
    concepts, members = set(), set()
    with open(G1B_PARSE / f"{vid}.facts.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r["concept"].rsplit("#", 1)[0] in ext_ns:
                concepts.add(r["concept"])
            for v in (r.get("dimensions") or {}).values():
                if v.startswith("E:") and v[2:].rsplit("#", 1)[0] in ext_ns:
                    members.add(v[2:])
    return concepts, members


def map_filing(issuer: str, fy: str):
    fid = f"{issuer}-{fy}"
    es = json.loads((STR / f"{fid}-es.structure.json").read_text(encoding="utf-8"))
    en = json.loads((STR / f"{fid}-en.structure.json").read_text(encoding="utf-8"))
    ext_es, ext_en = set(es["extension_namespaces"]), set(en["extension_namespaces"])
    ext_union = ext_es | ext_en

    es_all = {**es["ext_concepts"], **es["ext_members"]}
    en_all = {**en["ext_concepts"], **en["ext_members"]}
    es_facts, es_memb_used = fact_usage(f"{fid}-es", ext_es)
    en_facts, en_memb_used = fact_usage(f"{fid}-en", ext_en)

    def roles_of(q, all_ext, facts, memb_used):
        e = all_ext[q]
        r = []
        if q in facts:
            r.append("FACT_CONCEPT")
        if e.get("member_paths") or q in memb_used:
            r.append("DIMENSION_MEMBER")
        return r or ["FACT_CONCEPT"]

    # --- candidate indexes on the en side, per role, two tiers ---------
    # tier 1: signatures WITHOUT sibling order.  tier 2 (disambiguation):
    # ordered signatures, restricted to the tier-1 candidate set.  An
    # unordered-unique pairing keeps PROVEN even if order differs (recorded
    # as order_differs detail); order only decides between structurally
    # identical candidates, where position is the remaining evidence.
    def build_index(ordered):
        ci, mi = defaultdict(list), defaultdict(list)
        for q, e in en_all.items():
            ci[concept_sig(e, en_all, ext_union, ordered)].append(q)
            if e.get("member_paths"):
                mi[member_sig(e, en_all, ext_union, ordered)].append(q)
        return ci, mi

    en_ci1, en_mi1 = build_index(False)
    en_ci2, en_mi2 = build_index(True)

    def candidates(q, e, roles, ci, mi):
        sets = []
        if "FACT_CONCEPT" in roles:
            sets.append(set(ci.get(concept_sig(e, es_all, ext_union,
                                             ci is en_ci2), [])))
        if "DIMENSION_MEMBER" in roles:
            sets.append(set(mi.get(member_sig(e, es_all, ext_union,
                                              mi is en_mi2), [])))
        return set.intersection(*sets) if sets else set()

    cand1 = {q: candidates(q, e, roles_of(q, es_all, es_facts, es_memb_used),
                           en_ci1, en_mi1)
             for q, e in es_all.items()}
    en_back1 = defaultdict(list)
    for q_es, cs in cand1.items():
        for c in cs:
            en_back1[c].append(q_es)

    # tier 2 for ambiguous tier-1 results
    cand2 = {}
    en_back2 = defaultdict(list)
    for q, e in es_all.items():
        if len(cand1[q]) > 1:
            roles = roles_of(q, es_all, es_facts, es_memb_used)
            cs = candidates(q, e, roles, en_ci2, en_mi2) & cand1[q]
            cand2[q] = cs
            for c in cs:
                en_back2[c].append(q)

    records, pair_id = [], {}
    for q_es in sorted(es_all):
        e_es = es_all[q_es]
        roles = roles_of(q_es, es_all, es_facts, es_memb_used)
        cs1 = sorted(cand1[q_es])
        ev = []
        if "FACT_CONCEPT" in roles:
            ev += ["ANCHOR", "XBRL_PROPERTIES", "PRESENTATION_PATH",
                   "CALCULATION_ROLE"]
        if "DIMENSION_MEMBER" in roles:
            ev += ["DEFINITION_PATH"]
        rec = {"filing": fid, "source_qname": q_es, "target_qname": None,
               "mapping_type": "+".join(
                   "EXTENSION_CONCEPT" if r == "FACT_CONCEPT" else r
                   for r in roles),
               "evidence": ev}
        if len(cs1) == 1 and en_back1[cs1[0]] == [q_es]:
            q_en = cs1[0]
            pid = "PAIR::" + "::".join(sorted([q_es, q_en]))
            pair_id[q_es] = pair_id[q_en] = pid
            cs2 = candidates(q_es, e_es, roles, en_ci2, en_mi2)
            rec.update(target_qname=q_en, verdict="PROVEN_EQUIVALENT",
                       pair_id=pid,
                       detail={"tier": 1,
                               "order_differs": q_en not in cs2})
        elif cs1:
            cs2 = sorted(cand2.get(q_es, set()))
            if len(cs2) == 1 and en_back2[cs2[0]] == [q_es]:
                q_en = cs2[0]
                pid = "PAIR::" + "::".join(sorted([q_es, q_en]))
                pair_id[q_es] = pair_id[q_en] = pid
                rec.update(target_qname=q_en, verdict="PROVEN_EQUIVALENT",
                           pair_id=pid,
                           detail={"tier": 2,
                                   "order_disambiguated": True,
                                   "tier1_candidates": cs1})
            else:
                rec.update(verdict="AMBIGUOUS",
                           candidates=cs1,
                           ordered_candidates=cs2)
        else:
            # conflict probe: same anchoring, different properties/paths
            same_anchor = [q for q, e in en_all.items()
                           if anchor_sig(e) == anchor_sig(e_es)]
            rec.update(verdict="CONFLICT" if len(same_anchor) == 1
                       else "UNMATCHED",
                       anchor_matches=sorted(same_anchor))
        records.append(rec)
    for q_en in sorted(en_all):
        if q_en not in pair_id and not any(
                q_en in (r.get("candidates") or [])
                or r.get("target_qname") == q_en for r in records):
            records.append({"filing": fid, "source_qname": q_en,
                            "target_qname": None,
                            "mapping_type": "+".join(
                                "EXTENSION_CONCEPT" if r == "FACT_CONCEPT"
                                else r
                                for r in roles_of(q_en, en_all, en_facts,
                                                  en_memb_used)),
                            "evidence": ["ANCHOR", "DEFINITION_PATH"],
                            "verdict": "UNMATCHED", "direction": "en_only"})

    return {"filing": fid,
            "structure_es_sha256": sha_of(STR / f"{fid}-es.structure.json"),
            "structure_en_sha256": sha_of(STR / f"{fid}-en.structure.json"),
            "extension_namespaces": {"es": sorted(ext_es), "en": sorted(ext_en)},
            "fact_concepts_es": len(es_facts), "fact_concepts_en": len(en_facts),
            "dim_members_es": len(es_memb_used),
            "dim_members_en": len(en_memb_used),
            "records": sorted(records, key=lambda r: r["source_qname"])}


def adversarial_ambiguity_control():
    """Two es elements and two en elements with byte-identical structural
    signatures: the matcher must produce AMBIGUOUS, never a pairing."""
    fake = {"type": "xbrli#monetaryItemType", "periodType": "instant",
            "balance": "credit", "substitutionGroup": "xbrli#item",
            "abstract": False, "nillable": True,
            "anchors_to": [], "anchored_from": ["http://ifrs#ConceptA"],
            "pres_parents": [{"parent": "http://ifrs#AbstractP",
                              "order": 1.0, "role": "r"}],
            "calc_parents": [], "calc_children": []}
    es_all = {"ns-es#A": dict(fake), "ns-es#B": dict(fake)}
    en_all = {"ns-en#X": dict(fake), "ns-en#Y": dict(fake)}
    ext = {"ns-es", "ns-en"}
    en_idx = defaultdict(list)
    for q, e in en_all.items():
        en_idx[concept_sig(e, en_all, ext)].append(q)
    cand = {q: set(en_idx.get(concept_sig(e, es_all, ext), []))
            for q, e in es_all.items()}
    en_back = defaultdict(list)
    for q, cs in cand.items():
        for c in cs:
            en_back[c].append(q)
    paired = [q for q, cs in cand.items()
              if len(cs) == 1 and en_back[next(iter(cs))] == [q]]
    return {"pass": not paired and all(len(cs) == 2 for cs in cand.values()),
            "detail": "identical signatures must yield AMBIGUOUS, "
                      "never a pairing",
            "candidate_counts": {q: len(cs) for q, cs in cand.items()}}


def main():
    MAP.mkdir(parents=True, exist_ok=True)
    results = []
    for issuer, fy in DUAL:
        doc = map_filing(issuer, fy)
        recs = doc.pop("records")
        out = MAP / f"{issuer}-{fy}.mapping.json"
        out.write_bytes(json.dumps({"filing": doc["filing"],
                                    "records": recs},
                                   indent=1, ensure_ascii=False,
                                   sort_keys=True).encode("utf-8"))
        doc["mapping_sha256"] = sha_of(out)
        doc["verdict_counts"] = dict(Counter(r["verdict"] for r in recs))
        doc["proven_tier_counts"] = {
            "tier1_unique": sum(1 for r in recs
                                if r["verdict"] == "PROVEN_EQUIVALENT"
                                and r.get("detail", {}).get("tier") == 1),
            "tier2_order_disambiguated": sum(
                1 for r in recs if r["verdict"] == "PROVEN_EQUIVALENT"
                and r.get("detail", {}).get("tier") == 2)}
        doc["ambiguous_after_order"] = sum(
            1 for r in recs if r["verdict"] == "AMBIGUOUS")
        results.append(doc)
        print(doc["filing"], "->", doc["verdict_counts"], flush=True)

    checks = {"adversarial_ambiguity_control": adversarial_ambiguity_control()}
    (MAP / "mapping_results.json").write_text(json.dumps(
        {"results": results, "checks": checks}, indent=1, ensure_ascii=False,
        sort_keys=True), encoding="utf-8")
    print("adversarial:", checks["adversarial_ambiguity_control"]["pass"])
    print("wrote", MAP / "mapping_results.json")


if __name__ == "__main__":
    main()
