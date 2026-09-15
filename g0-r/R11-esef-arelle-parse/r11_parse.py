# R11 - ESEF_ARELLE_PARSE
# Conformance/integration test over Arelle 2.44.0 (authoritative engine).
# For each of the 6 ESEF report packages: offline load with R10-pinned
# taxonomy packages, ESEF validation, ModelXbrl API extraction, Arelle
# saveLoadableOIM export, and Control A (API vs OIM invariants).
import gzip, hashlib, json, logging, sys, time
from collections import Counter
from pathlib import Path

from arelle.RuntimeOptions import RuntimeOptions
from arelle.api.Session import Session
from arelle.XbrlConst import factFootnote
import arelle

REPO = Path(__file__).resolve().parents[2]
R07 = REPO / "g0-r/R07-raw-retrieval/evidence"
R10 = REPO / "g0-r/R10-taxonomy-pinning/evidence"
EV = Path(__file__).resolve().parent / "evidence"
EV.mkdir(exist_ok=True)

LEI_PKG = R10 / "xbrl-lei-2020-07-02-opencnmv-pkg.zip"
TAX = {
    "FY2024": {
        "disclosure": "esef-2022",
        "packages": [R10 / "esef_taxonomy_2022_v1.1.zip",
                     R10 / "ifrs-full_ifrs-2022-03-24-opencnmv-pkg.zip", LEI_PKG],
    },
    "FY2025": {
        "disclosure": "esef-2024",
        "packages": [R10 / "esef_taxonomy_2024.zip",
                     R10 / "ifrs-full_ifrs-2024-03-27-opencnmv-pkg.zip", LEI_PKG],
    },
}
FILINGS = [
    ("SAN-FY2024", "esef-SAN-FY2024-package.zip", "FY2024"),
    ("BBVA-FY2024", "esef-BBVA-FY2024-package.zip", "FY2024"),
    ("IBE-FY2024", "esef-IBE-FY2024-package.zip", "FY2024"),
    ("SAN-FY2025", "esef-SAN-FY2025-package.zip", "FY2025"),
    ("BBVA-FY2025", "esef-BBVA-FY2025-package.zip", "FY2025"),
    ("IBE-FY2025", "esef-IBE-FY2025-package.zip", "FY2025"),
]

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()

def qn(q):  # canonical QName
    return f"{q.namespaceURI}#{q.localName}"

def dim_repr(dim):
    if getattr(dim, "isExplicit", False):
        return "E:" + (qn(dim.memberQname) if dim.memberQname is not None else "nil")
    tv = getattr(dim, "typedMember", None)
    return "T:" + (tv.stringValue if tv is not None and hasattr(tv, "stringValue") else str(tv))

def ctx_sig(ctx):
    """Deterministic context signature: entity + period + sorted dimensions."""
    scheme, ident = ctx.entityIdentifier
    if ctx.isStartEndPeriod:
        period = f"{ctx.startDatetime.date()}/{ctx.endDatetime.date()}"
    elif ctx.isInstantPeriod:
        period = str(ctx.instantDatetime.date())
    else:
        period = "forever"
    dims = ";".join(f"{qn(d)}={dim_repr(v)}" for d, v in sorted(ctx.qnameDims.items(), key=lambda kv: qn(kv[0])))
    return f"{scheme}|{ident}|{period}|{dims}"

def unit_sig(unit):
    if unit is None:
        return ""
    num, den = unit.measures
    s = "*".join(sorted(qn(q) for q in num))
    if den:
        s += "/" + "*".join(sorted(qn(q) for q in den))
    return s

def _val_hash(v):
    if v is None:
        return None, 0, None
    b = v.encode("utf-8")
    return hashlib.sha256(b).hexdigest().upper(), len(b), v[:300]

def fact_record(f):
    ctx = f.context
    v_sha, v_len, v_prev = _val_hash(f.value)
    xv = str(f.xValue) if not f.isNil else None
    xv_sha, xv_len, xv_prev = _val_hash(xv)
    rec = {
        "concept": qn(f.qname),
        "value_sha256": v_sha,
        "value_len": v_len,
        "value_preview": v_prev,
        "xValue_sha256": xv_sha,
        "xValue_len": xv_len,
        "xValue_preview": xv_prev if xv_len and xv_len < 2000 else None,
        "isNil": bool(f.isNil),
        "decimals": str(f.decimals) if f.decimals is not None else None,
        "contextID": f.contextID,
        "unitID": f.unitID,
        "lang": f.xmlLang,
    }
    if ctx is not None:
        scheme, ident = ctx.entityIdentifier
        rec["entity_scheme"] = scheme
        rec["entity"] = ident
        if ctx.isStartEndPeriod:
            rec["period_start"] = str(ctx.startDatetime.date())
            rec["period_end"] = str(ctx.endDatetime.date())
        elif ctx.isInstantPeriod:
            rec["period_instant"] = str(ctx.instantDatetime.date())
        else:
            rec["period_forever"] = True
        rec["dimensions"] = {qn(d): dim_repr(v) for d, v in ctx.qnameDims.items()}
    if f.unit is not None:
        rec["unit"] = unit_sig(f.unit)
    return rec

def fact_key(rec):
    return "|".join([
        rec["concept"], rec.get("entity_scheme") or "", rec.get("entity") or "",
        rec.get("period_start") or "", rec.get("period_end") or "",
        rec.get("period_instant") or "", "1" if rec.get("period_forever") else "",
        rec.get("unit") or "", (rec.get("lang") or "") if not rec.get("unit") else "",
        ";".join(f"{k}={v}" for k, v in sorted(rec.get("dimensions", {}).items())),
    ])

def dts_docs(model):
    seen, stack = set(), [model.modelDocument]
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        stack.extend(getattr(d, "referencesDocument", {}).keys())
    return seen

def oim_fact_key(fact, nsmap):
    """Same normalised key built from an OIM JSON fact."""
    d = fact.get("dimensions", {})
    def resolve(v):
        if isinstance(v, str) and ":" in v:
            p, l = v.split(":", 1)
            if p in nsmap:
                return f"{nsmap[p]}#{l}"
        return v
    def norm_period(p):
        if "/" in p:
            a, b = p.split("/", 1)
            return (a.split("T")[0], b.split("T")[0], "", "")
        if p == "forever":
            return ("", "", "", "1")
        return ("", "", p.split("T")[0], "")
    concept = resolve(d.get("concept", ""))
    entity = d.get("entity", "")
    scheme, ident = "", entity
    if isinstance(entity, str) and ":" in entity:
        sch_q, ident = entity.rsplit(":", 1)
        scheme = nsmap.get(sch_q, sch_q)
    ps, pe, inst, forever = norm_period(d.get("period", ""))
    unit = d.get("unit", "")
    if isinstance(unit, str) and unit:
        parts = unit.split("/", 1)
        unit = "*".join(sorted(resolve(x) for x in parts[0].split("*")))
        if len(parts) > 1:
            unit += "/" + "*".join(sorted(resolve(x) for x in parts[1].split("*")))
    dims = {}
    for k, v in d.items():
        if k in ("concept", "entity", "period", "unit", "language", "noteId"):
            continue
        if isinstance(v, str) and ":" in v and resolve(v) != v:
            dims[resolve(k)] = "E:" + resolve(v)
        else:
            dims[resolve(k)] = "T:" + (v if isinstance(v, str) else json.dumps(v, sort_keys=True))
    return "|".join([concept, scheme, ident or "", ps, pe, inst, forever, unit or "",
                     d.get("language", "") if not unit else "",
                     ";".join(f"{k}={v}" for k, v in sorted(dims.items()))])

def run_filing(fid, zipname, fam):
    t0 = time.time()
    tax = TAX[fam]
    pkg = R07 / zipname
    oim_path = EV / f"{fid}.oim.json"
    opts = RuntimeOptions(
        entrypointFile=str(pkg),
        internetConnectivity="offline",
        packages=[str(p) for p in tax["packages"]],
        plugins="validate/ESEF|saveLoadableOIM",
        validate=True,
        disclosureSystemName=tax["disclosure"],
        keepOpen=True,
        pluginOptions={"saveLoadableOIM": str(oim_path)},
        logLevel="WARNING",
    )
    log_path = EV / f"{fid}.arelle-log.json"
    log_msgs = []

    class _H(logging.Handler):
        def emit(self, record):
            log_msgs.append({
                "level": record.levelname,
                "code": getattr(record, "messageCode", ""),
                "message": record.getMessage()[:500],
            })

    with Session() as s:
        run_ok = s.run(opts, logHandler=_H())
        models = s.get_models()
        log_path.write_text(json.dumps(log_msgs, indent=1, ensure_ascii=False), encoding="utf-8")
        if not models:
            return {"filing": fid, "status": "FAIL", "reason": "no model loaded"}
        m = models[0]

        # --- ModelXbrl / API extraction -------------------------------------
        records = [fact_record(f) for f in m.facts]
        records.sort(key=fact_key)
        facts_path = EV / f"{fid}.facts.jsonl"
        with open(facts_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

        ft = m.relationshipSet(factFootnote)
        footnote_rels = len(ft.modelRelationships) if ft else 0
        codes = Counter()
        for lm in log_msgs:
            codes[f'{lm.get("level", "?")}:{str(lm.get("code", "")).split(":", 1)[0]}'] += 1
        ioerrors = sum(1 for lm in log_msgs
                       if "Could not load" in str(lm.get("message", ""))
                       or "IOerror" in str(lm.get("code", "")))
        dl_attempts = sum(1 for lm in log_msgs if "retriev" in str(lm.get("message", "")).lower()
                          or "download" in str(lm.get("message", "")).lower())

        ns_domains = Counter()
        for q in m.qnameConcepts:
            ns_domains[q.namespaceURI.split("/")[2] if "/" in q.namespaceURI else q.namespaceURI] += 1

        typed_dims = sum(1 for c in m.contexts.values()
                         for d in c.qnameDims.values() if getattr(d, "isTyped", False))
        explicit_dims = sum(1 for c in m.contexts.values()
                            for d in c.qnameDims.values() if getattr(d, "isExplicit", False))
        nil_facts = sum(1 for r in records if r["isNil"])
        langs = sorted({r["lang"] for r in records if r["lang"]})

        summary = {
            "filing": fid,
            "package": pkg.name,
            "package_sha256": sha256_file(pkg),
            "arelle_version": arelle.__version__ if hasattr(arelle, "__version__") else "2.44.0",
            "runtime": {
                "internetConnectivity": "offline",
                "disclosureSystemName": tax["disclosure"],
                "plugins": "validate/ESEF|saveLoadableOIM",
                "validate": True,
                "taxonomy_packages": [p.name for p in tax["packages"]],
            },
            "run_ok": run_ok,
            "elapsed_s": round(time.time() - t0, 1),
            "counts": {
                "facts": len(records),
                "contexts": len(m.contexts),
                "units": len(m.units),
                "concepts": len(m.qnameConcepts),
                "dts_documents": len(dts_docs(m)),
                "fact_footnote_relationships": footnote_rels,
                "nil_facts": nil_facts,
                "contexts_explicit_dims": explicit_dims,
                "contexts_typed_dims": typed_dims,
                "fact_languages": langs,
            },
            "concept_namespaces": dict(ns_domains),
            "log_code_counts": dict(codes),
            "offline_evidence": {
                "io_errors": ioerrors,
                "download_attempts_in_log": dl_attempts,
            },
            "outputs": {
                "facts_jsonl": facts_path.name,
                "facts_jsonl_sha256": sha256_file(facts_path),
                "arelle_log": f"{fid}.arelle-log.json",
            },
        }

        # --- Control A: API vs OIM -------------------------------------------
        if oim_path.exists():
            summary["outputs"]["oim_json_sha256"] = sha256_file(oim_path)
            oim = json.loads(oim_path.read_text(encoding="utf-8"))
            nsmap = oim.get("documentInfo", {}).get("namespaces", {})
            api_keys = Counter(fact_key(r) for r in records)
            oim_facts = oim.get("facts", {})
            oim_keys = Counter(oim_fact_key(fo, nsmap) for fo in oim_facts.values())
            api_ctx = Counter(ctx_sig(c) for c in m.contexts.values())
            dec_api = Counter(str(r["decimals"]) for r in records)
            dec_oim = Counter(str(fo.get("decimals")) for fo in oim_facts.values())
            nil_oim = sum(1 for fo in oim_facts.values() if fo.get("value") is None)
            ctrl = {
                "fact_count_api": len(records),
                "fact_count_oim": len(oim_facts),
                "fact_multiset_equal": api_keys == oim_keys,
                "concept_coverage_equal": {qn(f.qname) for f in m.facts} ==
                    {oim_fact_key(fo, nsmap).split("|")[0] for fo in oim_facts.values()},
                "distinct_context_signatures_api": len(api_ctx),
                "decimals_distribution_equal": dec_api == dec_oim,
                "nil_count_api": nil_facts,
                "nil_count_oim": nil_oim,
            }
            # detail on mismatch, capped
            diff = list((api_keys - oim_keys).items())[:10] + [("OIM-ONLY", k) for k, v in list((oim_keys - api_keys).items())[:10]]
            ctrl["multiset_diff_sample"] = [str(d)[:300] for d in diff]
            summary["control_A"] = ctrl
            # gzip OIM for evidence compactness (deterministic mtime=0)
            gz_path = EV / f"{fid}.oim.json.gz"
            with open(oim_path, "rb") as fi, gzip.GzipFile(gz_path, "wb", mtime=0) as go:
                go.write(fi.read())
            oim_path.unlink()
            summary["outputs"]["oim_json_gz"] = gz_path.name
            summary["outputs"]["oim_json_gz_sha256"] = sha256_file(gz_path)
        else:
            summary["control_A"] = {"error": "OIM export file not produced"}

        (EV / f"{fid}.model_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

def main():
    sel = sys.argv[1] if len(sys.argv) > 1 else "all"
    results = []
    for fid, zipname, fam in FILINGS:
        if sel != "all" and fid != sel:
            continue
        print(f"=== {fid} ===", flush=True)
        s = run_filing(fid, zipname, fam)
        results.append(s)
        if "counts" in s:
            c = s["counts"]
            print(f"  facts={c['facts']} contexts={c['contexts']} units={c['units']} "
                  f"concepts={c['concepts']} dts={c['dts_documents']} ioerr={s['offline_evidence']['io_errors']} "
                  f"ctrlA={s.get('control_A', {}).get('fact_multiset_equal')}", flush=True)
    out = EV / "r11_results.json"
    prev = {r["filing"]: r for r in json.loads(out.read_text(encoding="utf-8"))} if out.exists() else {}
    prev.update({r["filing"]: r for r in results})
    merged = [prev[fid] for fid, _, _ in FILINGS if fid in prev]
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", out)

if __name__ == "__main__":
    main()
