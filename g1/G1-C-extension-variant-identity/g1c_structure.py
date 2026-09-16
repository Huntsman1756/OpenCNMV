# G1-C — EXTENSION_VARIANT_IDENTITY: structure extraction stage.
#
# Loads each unique variant package offline in Arelle 2.44.0 (identical
# runtime to G1-B extraction: same pinned taxonomies, same entrypoints) and
# dumps the *linkbase structure* needed to test cross-variant equivalence of
# issuer-extension elements:
#
#   concepts (issuer ext ns):
#     type / periodType / balance / substitutionGroup / abstract / nillable
#     anchoring: wider-narrower arc endpoints (ESEF anchoring linkbase)
#     presentation parents (parentChild arcs), per link role, with order
#     calculation parents/children (summationItem arcs, with weight)
#
#   dimension members (issuer ext ns elements appearing in domain-member
#   arcs, or used as E: members in the extracted facts):
#     paths: axis -> domain root -> parent chain -> member, with order/usable
#     (axis from hypercubeDimension+dimensionDomain; chain from domainMember)
#
# Equivalence decisions are NOT made here; this stage only serialises the
# authoritative DTS structure so the mapper can run deterministically on the
# JSON artefacts. Nothing re-implements XBRL semantics beyond reading Arelle
# relationship sets.
import hashlib, json, re, sys, time, zipfile
from pathlib import Path

from arelle.RuntimeOptions import RuntimeOptions
from arelle.api.Session import Session
from arelle.XbrlConst import (widerNarrower, parentChild, summationItem,
                              dimensionDomain, domainMember,
                              hypercubeDimension, dimensionDefault)
from arelle import Version

ARELLE_VERSION_EXPECTED = "2.44.0"
if getattr(Version, "version", None) != ARELLE_VERSION_EXPECTED:
    raise RuntimeError(f"pinned Arelle {ARELLE_VERSION_EXPECTED} required, "
                       f"found {getattr(Version, 'version', '?')}")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "g1/G1-B-dual-language-capture"))
from g1b_extract import VARIANTS, TAX, sha256_file  # noqa: E402

EV = HERE / "evidence" / "structure"
RUNS = HERE / "_runs"


def qn(q):
    return f"{q.namespaceURI}#{q.localName}"


def ext_namespaces(pkg: Path):
    out = set()
    with zipfile.ZipFile(pkg) as z:
        for n in z.namelist():
            if n.endswith(".xsd"):
                mm = re.search(rb'targetNamespace="([^"]+)"',
                               z.read(n)[:30000])
                if mm:
                    out.add(mm.group(1).decode("utf-8", "replace"))
    return out


def run_variant(vid, pkg: Path, fam, lang, out_dir: Path):
    t0 = time.time()
    opts = RuntimeOptions(
        entrypointFile=str(pkg),
        internetConnectivity="offline",
        packages=[str(p) for p in TAX[fam]["packages"]],
        validate=False, keepOpen=True, logLevel="ERROR")
    with Session() as s:
        s.run(opts)
        m = s.get_models()[0]
        ext_ns = ext_namespaces(pkg)

        wn = m.relationshipSet(widerNarrower)
        pc = m.relationshipSet(parentChild)
        si = m.relationshipSet(summationItem)
        dd = m.relationshipSet(dimensionDomain)
        dm = m.relationshipSet(domainMember)
        hd = m.relationshipSet(hypercubeDimension)
        df = m.relationshipSet(dimensionDefault)

        def _q(o):
            return qn(o.qname) if getattr(o, "qname", None) is not None else None

        anchors_out, anchors_in = {}, {}
        for r in (wn.modelRelationships if wn else []):
            a, b = _q(r.fromModelObject), _q(r.toModelObject)
            anchors_out.setdefault(a, []).append(b)
            anchors_in.setdefault(b, []).append(a)

        pres_par, pres_child = {}, {}
        for r in (pc.modelRelationships if pc else []):
            a, b = _q(r.fromModelObject), _q(r.toModelObject)
            pres_par.setdefault(b, []).append(
                {"parent": a, "order": r.order, "role": r.linkrole})
            pres_child.setdefault(a, []).append(
                {"child": b, "order": r.order, "role": r.linkrole})

        calc_par, calc_child = {}, {}
        for r in (si.modelRelationships if si else []):
            a, b = _q(r.fromModelObject), _q(r.toModelObject)
            calc_par.setdefault(b, []).append({"parent": a, "weight": r.weight})
            calc_child.setdefault(a, []).append({"child": b, "weight": r.weight})

        # --- dimension structure ---------------------------------------
        dim_dom = {}          # axis -> [domain roots]
        for r in (dd.modelRelationships if dd else []):
            dim_dom.setdefault(_q(r.fromModelObject), []).append(_q(r.toModelObject))
        dm_par = {}           # member -> [(parent, order, usable)]
        dm_child = {}
        for r in (dm.modelRelationships if dm else []):
            a, b = _q(r.fromModelObject), _q(r.toModelObject)
            dm_par.setdefault(b, []).append(
                {"parent": a, "order": r.order,
                 "usable": getattr(r, "usable", True)})
            dm_child.setdefault(a, []).append(b)
        hyp_axes = {}         # hypercube -> [axis]
        for r in (hd.modelRelationships if hd else []):
            hyp_axes.setdefault(_q(r.fromModelObject), []).append(_q(r.toModelObject))
        defaults = {}         # axis -> default member
        for r in (df.modelRelationships if df else []):
            defaults[_q(r.fromModelObject)] = _q(r.toModelObject)

        # member -> ancestor root domains (walk dm_par up to nodes with no
        # domainMember parent) then -> axes whose dimensionDomain points at
        # any node on the chain.
        def roots_of(member, seen=None):
            seen = seen or set()
            if member in seen:
                return []
            seen.add(member)
            pars = dm_par.get(member, [])
            if not pars:
                return [member]
            out = []
            for p in pars:
                out.extend(roots_of(p["parent"], seen))
            return out

        dom2axes = {}
        for ax, doms in dim_dom.items():
            for d in doms:
                dom2axes.setdefault(d, []).append(ax)

        ext_concepts, ext_members = {}, {}
        for c in m.qnameConcepts.values():
            q = qn(c.qname)
            ns = c.qname.namespaceURI
            if ns not in ext_ns:
                continue
            entry = {
                "type": qn(c.typeQname) if getattr(c, "typeQname", None) else None,
                "periodType": getattr(c, "periodType", None),
                "balance": getattr(c, "balance", None),
                "substitutionGroup": qn(c.substitutionGroupQname)
                    if getattr(c, "substitutionGroupQname", None) else None,
                "abstract": bool(getattr(c, "isAbstract", False)),
                "nillable": bool(getattr(c, "isNillable", False)),
                "anchors_to": sorted(set(anchors_out.get(q, []))),
                "anchored_from": sorted(set(anchors_in.get(q, []))),
                "pres_parents": sorted(pres_par.get(q, []),
                                       key=lambda d: (d["parent"] or "", d["order"])),
                "calc_parents": calc_par.get(q, []),
                "calc_children": calc_child.get(q, []),
            }
            if q in dm_par or q in dm_child:
                chains = []
                for p in dm_par.get(q, []):
                    # chain: walk up from parent to domain root
                    chain, node, seen = [], p["parent"], set()
                    while node and node not in seen:
                        seen.add(node)
                        chain.append(node)
                        ups = dm_par.get(node, [])
                        node = ups[0]["parent"] if ups else None
                    axes = sorted({ax for anc in chain
                                   for ax in dom2axes.get(anc, [])})
                    chains.append({"parent": p["parent"], "order": p["order"],
                                   "usable": p["usable"], "chain_up": chain,
                                   "axes": axes})
                entry["member_paths"] = chains
                ext_members[q] = entry
            else:
                ext_concepts[q] = entry

        doc = {
            "variant": vid, "lang": lang, "family": fam,
            "package": str(pkg.relative_to(REPO)),
            "package_sha256": sha256_file(pkg),
            "extension_namespaces": sorted(ext_ns),
            "relationship_counts": {
                "widerNarrower": len(wn.modelRelationships) if wn else 0,
                "parentChild": len(pc.modelRelationships) if pc else 0,
                "summationItem": len(si.modelRelationships) if si else 0,
                "dimensionDomain": len(dd.modelRelationships) if dd else 0,
                "domainMember": len(dm.modelRelationships) if dm else 0,
                "hypercubeDimension": len(hd.modelRelationships) if hd else 0,
                "dimensionDefault": len(df.modelRelationships) if df else 0,
            },
            "ext_concepts": ext_concepts,
            "ext_members": ext_members,
        }
        p = out_dir / f"{vid}.structure.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1),
                     encoding="utf-8")
        doc["structure_sha256"] = sha256_file(p)
        doc["elapsed_s"] = round(time.time() - t0, 1)
        return doc


def main():
    ap_run = sys.argv[1] if len(sys.argv) > 1 else "1"
    sel = sys.argv[2] if len(sys.argv) > 2 else "all"
    out_dir = EV if ap_run == "1" else RUNS / f"structure-run{ap_run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for vid, pkg, fam, lang in VARIANTS:
        if sel != "all" and vid != sel:
            continue
        print(f"=== {vid} ===", flush=True)
        d = run_variant(vid, pkg, fam, lang, out_dir)
        results[vid] = d
        print(f"  ext_concepts={len(d['ext_concepts'])} ext_members={len(d['ext_members'])} "
              f"wn={d['relationship_counts']['widerNarrower']} "
              f"dm={d['relationship_counts']['domainMember']}", flush=True)
    res_path = out_dir / "structure_results.json"
    prev = {}
    if res_path.exists():
        prev = {r["variant"]: r for r in json.loads(res_path.read_text(encoding="utf-8"))}
    slim = {v: {"variant": v, "package_sha256": d["package_sha256"],
                "structure_sha256": d["structure_sha256"],
                "ext_concepts": len(d["ext_concepts"]),
                "ext_members": len(d["ext_members"]),
                "relationship_counts": d["relationship_counts"],
                "elapsed_s": d["elapsed_s"]}
            for v, d in results.items()}
    prev.update(slim)
    res_path.write_text(json.dumps(
        [prev[v[0]] for v in VARIANTS if v[0] in prev],
        indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", res_path)


if __name__ == "__main__":
    main()
