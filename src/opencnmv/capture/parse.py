"""Offline parse stage for captured artifacts.

Promotes the gate-proven extraction paths into production:

  * ``parse_state``            — one ParseSession per variant version ->
                                 canonical fact records + unit sidecar
                                 (same contract as g2c_parse_one).
  * ``extract_structure``      — linkbase structure of issuer-extension
                                 elements (G1-C stage 1, from a live
                                 Arelle model inside the same session).
  * ``map_variants``           — cross-variant extension pairing with the
                                 G1-C verdict vocabulary (PROVEN /
                                 AMBIGUOUS / CONFLICT / UNMATCHED);
                                 labels are never used.

Parsing only ever runs on preserved bytes under the pinned taxonomy set;
the session is offline (``internetConnectivity="offline"``).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from opencnmv.canonicalize import facts as xfacts
from opencnmv.capture.contract import CaptureError
from opencnmv.xbrl import arelle as xarelle
from opencnmv.xbrl import taxonomy as xtax


def parse_state(artifact: Path, *, kind: str, fy: str | None,
                tax_dir: Path, work_dir: Path, name: str) -> dict:
    """Facts + units + structure for one variant version's artifact.

    ``kind`` is ``"esef"`` (report package zip) or ``"ipp"`` (raw xbrl
    instance bytes). Returns facts/units plus parse metadata for the
    provenance row. Structure extraction runs inside the same session so
    a changed filing costs exactly one Arelle load.
    """
    tax_dir = Path(tax_dir)
    if kind == "esef":
        if fy is None:
            raise CaptureError("esef parse requires a fiscal year")
        tax = xtax.esef_taxonomy_set(fy, tax_dir)
    else:
        tax = xtax.ipp_taxonomy_set(tax_dir)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    entry = (artifact if kind == "esef" else
             xarelle.prepare_xbrl_entrypoint(artifact, work_dir, name))
    spec = xarelle.ParseSpec(
        entrypoint=str(entry),
        taxonomy_packages=tax["packages"],
        disclosure_system=tax["disclosure"],
        plugins=("validate/ESEF|saveLoadableOIM" if kind == "esef"
                 else "saveLoadableOIM"),
        validate=True,
        lexical_shim=(kind == "ipp"))
    with xarelle.ParseSession(spec) as sess:
        m = sess.model
        if m is None:
            raise CaptureError(f"{name}: Arelle loaded no model")
        ext_ns = (xtax.extension_namespaces(artifact)
                  if kind == "esef" else set())
        pairs = [(xfacts.fact_record(f, profile=kind,
                                   ext_ns=(ext_ns or None)),
                  f.unit) for f in m.facts]
        pairs.sort(key=lambda p: xfacts.fact_sort_key(p[0]))
        units = [{"num": sorted(xfacts.qn(q) for q in u.measures[0]),
                  "den": sorted(xfacts.qn(q) for q in u.measures[1])}
                 if u is not None else {"num": [], "den": []}
                 for _r, u in pairs]
        structure = (extract_structure(m, ext_ns) if kind == "esef"
                     else None)
        io_errors = sum(
            1 for lm in sess.log_msgs
            if "Could not load" in str(lm.get("message", ""))
            or "IOerror" in str(lm.get("code", "")))
        return {"facts": [p[0] for p in pairs], "units": units,
                "arelle_version": xarelle.ARELLE_VERSION,
                "lexical_shim": bool(getattr(sess, "shim_info", None)),
                "run_ok": sess.run_ok,
                "io_errors": io_errors,
                "extension_namespaces": sorted(ext_ns),
                "structure": structure}


# ---- linkbase structure (G1-C stage 1, promoted) ---------------------------

def _qn(q) -> str:
    return f"{q.namespaceURI}#{q.localName}"


def extract_structure(model, ext_ns: set[str]) -> dict:
    """Issuer-extension DTS structure from a loaded Arelle model.

    Serialises exactly the relationships G1-C mapped on: XBRL properties,
    wider-narrower anchoring, presentation parents (with order), and
    calculation parents/children (with weight); plus domain-member paths
    for dimension members. Deterministic given the DTS.
    """
    from arelle.XbrlConst import (dimensionDefault, dimensionDomain,
                                  domainMember, hypercubeDimension,
                                  parentChild, summationItem,
                                  widerNarrower)

    def rel(name):
        rs = model.relationshipSet(name)
        return rs.modelRelationships if rs else []

    def _q(o):
        return _qn(o.qname) if getattr(o, "qname", None) is not None \
            else None

    anchors_out: dict = defaultdict(list)
    anchors_in: dict = defaultdict(list)
    for r in rel(widerNarrower):
        anchors_out[_q(r.fromModelObject)].append(_q(r.toModelObject))
        anchors_in[_q(r.toModelObject)].append(_q(r.fromModelObject))

    pres_par: dict = defaultdict(list)
    for r in rel(parentChild):
        pres_par[_q(r.toModelObject)].append(
            {"parent": _q(r.fromModelObject), "order": r.order,
             "role": r.linkrole})

    calc_par: dict = defaultdict(list)
    calc_child: dict = defaultdict(list)
    for r in rel(summationItem):
        a, b = _q(r.fromModelObject), _q(r.toModelObject)
        calc_par[b].append({"parent": a, "weight": r.weight})
        calc_child[a].append({"child": b, "weight": r.weight})

    dim_dom: dict = defaultdict(list)
    for r in rel(dimensionDomain):
        dim_dom[_q(r.fromModelObject)].append(_q(r.toModelObject))
    dm_par: dict = defaultdict(list)
    dm_child: dict = defaultdict(list)
    for r in rel(domainMember):
        a, b = _q(r.fromModelObject), _q(r.toModelObject)
        dm_par[b].append({"parent": a, "order": r.order,
                          "usable": getattr(r, "usable", True)})
        dm_child[a].append(b)
    dom2axes: dict = defaultdict(set)
    for r in rel(hypercubeDimension):
        ax = _q(r.toModelObject)
        for d in dim_dom.get(_q(r.fromModelObject), []):
            dom2axes[d].add(ax)
    for r in rel(dimensionDefault):  # structure completeness, unused
        pass

    def roots_of(member, seen):
        if member in seen:
            return []
        seen.add(member)
        pars = dm_par.get(member, [])
        if not pars:
            return [member]
        out: list = []
        for p in pars:
            out.extend(roots_of(p["parent"], seen))
        return out

    ext_concepts: dict = {}
    ext_members: dict = {}
    for c in model.qnameConcepts.values():
        if c.qname.namespaceURI not in ext_ns:
            continue
        q = _qn(c.qname)
        entry = {
            "type": _qn(c.typeQname)
            if getattr(c, "typeQname", None) else None,
            "periodType": getattr(c, "periodType", None),
            "balance": getattr(c, "balance", None),
            "substitutionGroup": _qn(c.substitutionGroupQname)
            if getattr(c, "substitutionGroupQname", None) else None,
            "abstract": bool(getattr(c, "isAbstract", False)),
            "nillable": bool(getattr(c, "isNillable", False)),
            "anchors_to": sorted(set(anchors_out.get(q, []))),
            "anchored_from": sorted(set(anchors_in.get(q, []))),
            "pres_parents": sorted(pres_par.get(q, []),
                                   key=lambda d: (d["parent"] or "",
                                                  d["order"])),
            "calc_parents": calc_par.get(q, []),
            "calc_children": calc_child.get(q, []),
        }
        if q in dm_par or q in dm_child:
            chains = []
            for p in dm_par.get(q, []):
                chain, node, seen = [], p["parent"], set()
                while node and node not in seen:
                    seen.add(node)
                    chain.append(node)
                    ups = dm_par.get(node, [])
                    node = ups[0]["parent"] if ups else None
                axes = sorted({ax for anc in chain
                               for ax in dom2axes.get(anc, set())})
                chains.append({"parent": p["parent"], "order": p["order"],
                               "usable": p["usable"], "chain_up": chain,
                               "axes": axes})
            entry["member_paths"] = chains
            ext_members[q] = entry
        else:
            ext_concepts[q] = entry
    return {"extension_namespaces": sorted(ext_ns),
            "ext_concepts": ext_concepts, "ext_members": ext_members}


# ---- cross-variant extension mapping (G1-C stage 2, promoted) --------------

def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _props_sig(e) -> str:
    return json.dumps([e.get("type"), e.get("periodType"),
                       e.get("balance"), e.get("substitutionGroup"),
                       e.get("abstract"), e.get("nillable")],
                      sort_keys=True)


def _anchor_sig(e) -> str:
    return json.dumps([sorted(e.get("anchors_to") or []),
                       sorted(e.get("anchored_from") or [])],
                      sort_keys=True)


def _node_sig(q, all_ext, ext_ns):
    """Structural signature of a *referenced* node in a linkbase path."""
    if q is None:
        return ("?", "nil")
    if q.rsplit("#", 1)[0] not in ext_ns:
        return ("T", q)
    e = all_ext.get(q)
    if e is None:
        return ("X", "unseen", q.rsplit("#", 1)[-1])
    return ("X", _anchor_sig(e), _props_sig(e))


def _pres_sig(entry, all_ext, ext_ns, ordered=False):
    sig = [(_node_sig(p["parent"], all_ext, ext_ns), p["order"])
           for p in entry.get("pres_parents") or []]
    if not ordered:
        sig = [s[0] for s in sig]
    return sorted(map(repr, sig))


def _calc_sig(entry, all_ext, ext_ns):
    par = sorted(repr((_node_sig(p["parent"], all_ext, ext_ns),
                       p["weight"]))
                 for p in entry.get("calc_parents") or [])
    chi = sorted(repr((_node_sig(c["child"], all_ext, ext_ns),
                       c["weight"]))
                 for c in entry.get("calc_children") or [])
    return (par, chi)


def _member_sig(entry, all_ext, ext_ns, ordered=False):
    out = []
    for p in entry.get("member_paths") or []:
        d = {"axes": sorted(repr(_node_sig(a, all_ext, ext_ns))
                            for a in p["axes"]),
             "chain": [repr(_node_sig(n, all_ext, ext_ns))
                       for n in p["chain_up"]],
             "usable": p["usable"]}
        if ordered:
            d["order"] = p["order"]
        out.append(d)
    return _canon(sorted(out, key=lambda d: _canon(d).decode()))


def _concept_sig(entry, all_ext, ext_ns, ordered=False):
    return (_props_sig(entry), _anchor_sig(entry),
            tuple(_pres_sig(entry, all_ext, ext_ns, ordered)),
            repr(_calc_sig(entry, all_ext, ext_ns)))


def _fact_usage(records: list[dict], ext_ns: set[str]):
    """ext elements bearing facts, and ext elements used as dim members."""
    concepts, members = set(), set()
    for r in records:
        if r["concept"].rsplit("#", 1)[0] in ext_ns:
            concepts.add(r["concept"])
        for v in (r.get("dimensions") or {}).values():
            if v.startswith("E:") and v[2:].rsplit("#", 1)[0] in ext_ns:
                members.add(v[2:])
    return concepts, members


def map_variants(filing_id: str, es_struct: dict, en_struct: dict,
                 es_facts: list[dict], en_facts: list[dict]
                 ) -> list[dict]:
    """Pair issuer-extension elements across the es/en variants.

    Pure function of extracted structure + fact usage — the same verdict
    vocabulary and evidence rules as G1-C (labels are never consulted).
    """
    ext_es = set(es_struct["extension_namespaces"])
    ext_en = set(en_struct["extension_namespaces"])
    ext_union = ext_es | ext_en

    es_all = {**es_struct["ext_concepts"], **es_struct["ext_members"]}
    en_all = {**en_struct["ext_concepts"], **en_struct["ext_members"]}
    es_facts_c, es_memb = _fact_usage(es_facts, ext_es)
    en_facts_c, en_memb = _fact_usage(en_facts, ext_en)

    def roles_of(q, all_ext, facts, memb_used):
        e = all_ext[q]
        r = []
        if q in facts:
            r.append("FACT_CONCEPT")
        if e.get("member_paths") or q in memb_used:
            r.append("DIMENSION_MEMBER")
        return r or ["FACT_CONCEPT"]

    def build_index(ordered):
        ci: dict = defaultdict(list)
        mi: dict = defaultdict(list)
        for q, e in en_all.items():
            ci[_concept_sig(e, en_all, ext_union, ordered)].append(q)
            if e.get("member_paths"):
                mi[_member_sig(e, en_all, ext_union, ordered)].append(q)
        return ci, mi

    en_ci1, en_mi1 = build_index(False)
    en_ci2, en_mi2 = build_index(True)

    def candidates(q, e, roles, ci, mi):
        ordered = ci is en_ci2
        sets = []
        if "FACT_CONCEPT" in roles:
            sets.append(set(ci.get(
                _concept_sig(e, es_all, ext_union, ordered), [])))
        if "DIMENSION_MEMBER" in roles:
            sets.append(set(mi.get(
                _member_sig(e, es_all, ext_union, ordered), [])))
        return set.intersection(*sets) if sets else set()

    cand1 = {q: candidates(q, e,
                           roles_of(q, es_all, es_facts_c, es_memb),
                           en_ci1, en_mi1)
             for q, e in es_all.items()}
    en_back1: dict = defaultdict(list)
    for q_es, cs in cand1.items():
        for c in cs:
            en_back1[c].append(q_es)

    cand2: dict = {}
    en_back2: dict = defaultdict(list)
    for q, e in es_all.items():
        if len(cand1[q]) > 1:
            roles = roles_of(q, es_all, es_facts_c, es_memb)
            cs = candidates(q, e, roles, en_ci2, en_mi2) & cand1[q]
            cand2[q] = cs
            for c in cs:
                en_back2[c].append(q)

    records: list = []
    pair_id: dict = {}
    for q_es in sorted(es_all):
        e_es = es_all[q_es]
        roles = roles_of(q_es, es_all, es_facts_c, es_memb)
        cs1 = sorted(cand1[q_es])
        ev = []
        if "FACT_CONCEPT" in roles:
            ev += ["ANCHOR", "XBRL_PROPERTIES", "PRESENTATION_PATH",
                   "CALCULATION_ROLE"]
        if "DIMENSION_MEMBER" in roles:
            ev += ["DEFINITION_PATH"]
        rec = {"filing": filing_id, "source_qname": q_es,
               "target_qname": None,
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
                rec.update(verdict="AMBIGUOUS", candidates=cs1,
                           ordered_candidates=cs2)
        else:
            same_anchor = [q for q, e in en_all.items()
                           if _anchor_sig(e) == _anchor_sig(e_es)]
            rec.update(verdict="CONFLICT" if len(same_anchor) == 1
                       else "UNMATCHED",
                       anchor_matches=sorted(same_anchor))
        records.append(rec)
    for q_en in sorted(en_all):
        if q_en not in pair_id and not any(
                q_en in (r.get("candidates") or [])
                or r.get("target_qname") == q_en for r in records):
            records.append({
                "filing": filing_id, "source_qname": q_en,
                "target_qname": None,
                "mapping_type": "+".join(
                    "EXTENSION_CONCEPT" if r == "FACT_CONCEPT" else r
                    for r in roles_of(q_en, en_all, en_facts_c,
                                      en_memb)),
                "evidence": ["ANCHOR", "DEFINITION_PATH"],
                "verdict": "UNMATCHED", "direction": "en_only"})
    return sorted(records, key=lambda r: r["source_qname"])
