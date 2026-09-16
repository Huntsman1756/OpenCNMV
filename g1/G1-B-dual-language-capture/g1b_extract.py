# G1-B — extraction stage: offline Arelle parse of every UNIQUE submitted
# variant artifact set (6 x -es + 4 x -en; IBE contributes one variant each,
# its lang=en view having resolved to the -es bytes in G1-B capture).
#
# EXTRACT/ADAPT decision (AGENTS.md rule 2): this file is a thin adapted copy
# of the R11 ESEF harness (g0-r/R11-esef-arelle-parse/r11_parse.py). Arelle
# 2.44.0 remains the authoritative parser/validator; nothing here re-implements
# XBRL semantics. Additions vs R11, needed for cross-variant comparison:
#   * concept_type (item type QName) — language-sensitivity classification
#   * is_numeric flag
#   * value/xValue stored in full when short (<=512 chars) — needed to detect
#     numeric equivalence ("0.10" vs "0.1") and divergent payloads
#   * extension_namespaces — targetNamespaces declared by schemas inside the
#     report package itself (issuer extension), vs pinned taxonomy packages
#   * per-variant naming (issuer-FY-lang), package resolved by explicit path
# Determinism: identical package bytes + pinned taxonomies -> identical
# facts.jsonl sha256. Run twice (--run 1|2); run1 is committed evidence, run2
# is a gitignored rebuild compared by sha.
import gzip, hashlib, json, logging, re, sys, time, zipfile
from collections import Counter
from pathlib import Path

from arelle.RuntimeOptions import RuntimeOptions
from arelle.api.Session import Session
from arelle.XbrlConst import factFootnote
import arelle
from arelle import Version

ARELLE_VERSION_EXPECTED = "2.44.0"
if getattr(Version, "version", None) != ARELLE_VERSION_EXPECTED:
    raise RuntimeError(f"pinned Arelle {ARELLE_VERSION_EXPECTED} required, "
                       f"found {getattr(Version, 'version', '?')}")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
R07 = REPO / "g0-r/R07-raw-retrieval/evidence"
G1A_EV = REPO / "g1/G1-A-oam-variant-discovery/evidence"
R10 = REPO / "g0-r/R10-taxonomy-pinning/evidence"
EV = HERE / "evidence" / "parse"
RUNS = HERE / "_runs"

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

def _es(i, fy):
    return (f"{i}-{fy}-es", R07 / f"esef-{i}-{fy}-package.zip", fy, "es")
def _en(i, fy):
    return (f"{i}-{fy}-en", G1A_EV / f"esef-{i}-{fy}-en.zip", fy, "en")

VARIANTS = [
    _es("SAN", "FY2024"), _en("SAN", "FY2024"),
    _es("SAN", "FY2025"), _en("SAN", "FY2025"),
    _es("BBVA", "FY2024"), _en("BBVA", "FY2024"),
    _es("BBVA", "FY2025"), _en("BBVA", "FY2025"),
    _es("IBE", "FY2024"),
    _es("IBE", "FY2025"),
]

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()

def qn(q):
    return f"{q.namespaceURI}#{q.localName}"

def dim_repr(dim):
    if getattr(dim, "isExplicit", False):
        return "E:" + (qn(dim.memberQname) if dim.memberQname is not None else "nil")
    tv = getattr(dim, "typedMember", None)
    return "T:" + (tv.stringValue if tv is not None and hasattr(tv, "stringValue") else str(tv))

def ctx_sig(ctx):
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

def _val(v):
    b = v.encode("utf-8")
    return (hashlib.sha256(b).hexdigest().upper(), len(b), v[:300],
            v if len(b) <= 512 else None)

def fact_record(f):
    ctx = f.context
    v_sha, v_len, v_prev, v_full = _val(f.value) if f.value is not None else (None, 0, None, None)
    xv = str(f.xValue) if not f.isNil else None
    xv_sha, xv_len, xv_prev, xv_full = _val(xv) if xv is not None else (None, 0, None, None)
    ctype = None
    if getattr(f, "concept", None) is not None and getattr(f.concept, "typeQname", None) is not None:
        ctype = qn(f.concept.typeQname)
    rec = {
        "concept": qn(f.qname),
        "concept_type": ctype,
        "is_numeric": bool(getattr(f, "isNumeric", False)),
        "value_sha256": v_sha, "value_len": v_len,
        "value_preview": v_prev, "value_full": v_full,
        "xValue_sha256": xv_sha, "xValue_len": xv_len,
        "xValue_preview": xv_prev, "xValue_full": xv_full,
        "isNil": bool(f.isNil),
        "decimals": str(f.decimals) if f.decimals is not None else None,
        "contextID": f.contextID, "unitID": f.unitID,
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

def run_variant(vid, pkg: Path, fam, lang, out_dir: Path):
    t0 = time.time()
    tax = TAX[fam]
    oim_path = out_dir / f"{vid}.oim.json"
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
    log_msgs = []

    class _H(logging.Handler):
        def emit(self, record):
            log_msgs.append({"level": record.levelname,
                             "code": getattr(record, "messageCode", ""),
                             "message": record.getMessage()[:500]})

    with Session() as s:
        run_ok = s.run(opts, logHandler=_H())
        models = s.get_models()
        (out_dir / f"{vid}.arelle-log.json").write_text(
            json.dumps(log_msgs, indent=1, ensure_ascii=False), encoding="utf-8")
        if not models:
            return {"variant": vid, "status": "FAIL", "reason": "no model loaded"}
        m = models[0]

        # issuer-extension namespaces: targetNamespaces declared by the .xsd
        # schemas embedded in the report package itself (taxonomy schemas are
        # referenced via pinned packages, never embedded). Read straight from
        # the preserved zip bytes - deterministic, no DTS internals needed.
        ext_ns = set()
        with zipfile.ZipFile(pkg) as z:
            for n in z.namelist():
                if n.endswith(".xsd"):
                    mm = re.search(rb'targetNamespace="([^"]+)"',
                                   z.read(n)[:30000])
                    if mm:
                        ext_ns.add(mm.group(1).decode("utf-8", "replace"))

        records = [fact_record(f) for f in m.facts]
        for r in records:
            ns = r["concept"].rsplit("#", 1)[0]
            r["ns_kind"] = "issuer_extension" if ns in ext_ns else "taxonomy"
        records.sort(key=fact_key)
        facts_path = out_dir / f"{vid}.facts.jsonl"
        with open(facts_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

        ft = m.relationshipSet(factFootnote)
        codes = Counter(f'{lm.get("level", "?")}:{str(lm.get("code", "")).split(":", 1)[0]}'
                        for lm in log_msgs)
        ioerrors = sum(1 for lm in log_msgs
                       if "Could not load" in str(lm.get("message", ""))
                       or "IOerror" in str(lm.get("code", "")))
        dl = sum(1 for lm in log_msgs
                 if "retriev" in str(lm.get("message", "")).lower()
                 or "download" in str(lm.get("message", "")).lower())

        summary = {
            "variant": vid, "lang": lang, "family": fam,
            "package": str(pkg.relative_to(REPO)),
            "package_sha256": sha256_file(pkg),
            "arelle_version": getattr(Version, "version", "?"),
            "runtime": {"internetConnectivity": "offline",
                        "disclosureSystemName": tax["disclosure"],
                        "plugins": "validate/ESEF|saveLoadableOIM",
                        "validate": True,
                        "taxonomy_packages": [p.name for p in tax["packages"]]},
            "run_ok": run_ok, "elapsed_s": round(time.time() - t0, 1),
            "counts": {
                "facts": len(records), "contexts": len(m.contexts),
                "units": len(m.units), "concepts": len(m.qnameConcepts),
                "dts_documents": len(dts_docs(m)),
                "fact_footnote_relationships": len(ft.modelRelationships) if ft else 0,
                "nil_facts": sum(1 for r in records if r["isNil"]),
                "fact_languages": sorted({r["lang"] for r in records if r["lang"]}),
                "facts_extension_ns": sum(1 for r in records
                                          if r["ns_kind"] == "issuer_extension"),
            },
            "extension_namespaces": sorted(ext_ns),
            "log_code_counts": dict(codes),
            "offline_evidence": {"io_errors": ioerrors, "download_attempts_in_log": dl},
            "outputs": {"facts_jsonl": facts_path.name,
                        "facts_jsonl_sha256": sha256_file(facts_path)},
        }

        if oim_path.exists():
            summary["outputs"]["oim_json_sha256"] = sha256_file(oim_path)
            oim = json.loads(oim_path.read_text(encoding="utf-8"))
            nsmap = oim.get("documentInfo", {}).get("namespaces", {})
            api_keys = Counter(fact_key(r) for r in records)
            oim_facts = oim.get("facts", {})
            oim_keys = Counter(oim_fact_key(fo, nsmap) for fo in oim_facts.values())
            dec_api = Counter(str(r["decimals"]) for r in records)
            dec_oim = Counter(str(fo.get("decimals")) for fo in oim_facts.values())
            summary["control_A"] = {
                "fact_count_api": len(records),
                "fact_count_oim": len(oim_facts),
                "fact_multiset_equal": api_keys == oim_keys,
                "concept_coverage_equal": {qn(f.qname) for f in m.facts} ==
                    {oim_fact_key(fo, nsmap).split("|")[0] for fo in oim_facts.values()},
                "decimals_distribution_equal": dec_api == dec_oim,
                "nil_count_api": summary["counts"]["nil_facts"],
                "nil_count_oim": sum(1 for fo in oim_facts.values()
                                     if fo.get("value") is None),
            }
            gz_path = out_dir / f"{vid}.oim.json.gz"
            with open(oim_path, "rb") as fi, gzip.GzipFile(gz_path, "wb", mtime=0) as go:
                go.write(fi.read())
            oim_path.unlink()
            summary["outputs"]["oim_json_gz_sha256"] = sha256_file(gz_path)
        else:
            summary["control_A"] = {"error": "OIM export file not produced"}

        (out_dir / f"{vid}.model_summary.json").write_text(
            json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
        return summary

def main():
    ap_run = sys.argv[1] if len(sys.argv) > 1 else "1"
    sel = sys.argv[2] if len(sys.argv) > 2 else "all"
    out_dir = EV / "run1" if ap_run == "1" else RUNS / f"extract-run{ap_run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for vid, pkg, fam, lang in VARIANTS:
        if sel != "all" and vid != sel:
            continue
        print(f"=== {vid} ===", flush=True)
        s = run_variant(vid, pkg, fam, lang, out_dir)
        results[vid] = s
        if "counts" in s:
            c = s["counts"]
            print(f"  facts={c['facts']} ext_ns_facts={c['facts_extension_ns']} "
                  f"langs={c['fact_languages']} ioerr={s['offline_evidence']['io_errors']} "
                  f"ctrlA={s.get('control_A', {}).get('fact_multiset_equal')}", flush=True)
    prev = {}
    res_path = out_dir / "extract_results.json"
    if res_path.exists():
        prev = {r["variant"]: r for r in json.loads(res_path.read_text(encoding="utf-8"))}
    prev.update(results)
    res_path.write_text(json.dumps(
        [prev[v[0]] for v in VARIANTS if v[0] in prev],
        indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", res_path)

if __name__ == "__main__":
    main()
