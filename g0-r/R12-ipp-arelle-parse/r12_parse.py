# R12 - IPP_ARELLE_PARSE
# Conformance/integration test over Arelle 2.44.0 (authoritative engine),
# reusing the R11 harness pattern on the 15 raw IPP XBRL instances (R7).
# Covers the credit-entity model (ipp_en: SAN/BBVA), the general model
# (ipp_ge: IBE), H1 and H2 slots, and the taxonomy/model heterogeneity
# actually observed in the frozen corpus.
#
# Documented engine workaround (Arelle limitation, not a taxonomy failure):
# arelle.XmlValidate.lexicalPatterns["base64Binary"] is a nested-quantifier
# regex that raises MemoryError on the ~8 MB base64Binary facts the IPP
# instances carry (ipp_*:InformacionFinancieraSemestralContenido /
# ipp_*:InformeCompleto*_Contenido - embedded PDF bytes, type
# xbrli:base64BinaryItemType). Identical regex present in arelle-release
# 2.45.0, so upgrading does not fix it. The shim below is a linear-time
# equivalent of the same XSD lexical pattern (whitespace-insensitive quads,
# padding restricted to the final quad, zero-bit pad semantics). XBRL
# semantics are untouched; facts are preserved raw.
import base64, gzip, hashlib, json, logging, re, shutil, sys, time
from collections import Counter
from pathlib import Path

import arelle.XmlValidate as _XV
from arelle.RuntimeOptions import RuntimeOptions
from arelle.api.Session import Session
from arelle.XbrlConst import factFootnote
import arelle

_B64SET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
_WSSET = frozenset(" \t\n\r")
_B64_R1 = frozenset("AEIMQUYcgkosw048")   # allowed char before single '='
_B64_R2 = frozenset("AQgw")              # allowed char before '=='

class _LinearBase64:
    """O(n) equivalent of lexicalPatterns['base64Binary'] (callers only test
    truthiness). Faithful to the original regex-module (V0) semantics, which
    were mapped empirically: each base64 char may be followed by AT MOST ONE
    whitespace; whitespace is internal only - the last meaningful char must be
    a base64 char or '='; a single trailing '\\n' is tolerated by the '$'
    anchor (it matches before a final newline without consuming it); padding
    '=' is confined to the final quad with the pad-adjacent character
    restricted so unused bits are zero."""
    def match(self, value):
        if value.endswith("\n"):
            value = value[:-1]            # '$' permits one final '\n'
        n = len(value)
        if n == 0:
            return True
        if value[n - 1] in _WSSET:
            return None                   # no other trailing whitespace
        i, cnt, last = 0, 0, None
        while i < n:
            ch = value[i]
            if ch in _B64SET:
                last = ch
                cnt += 1
                i += 1
                if i < n and value[i] in _WSSET:
                    i += 1
            else:
                break
        if i == n:
            return True if cnt % 4 == 0 else None
        if value[i] != "=":
            return None
        t = cnt % 4
        if t == 3:                        # tail: B B R1 '='
            if last not in _B64_R1:
                return None
            return True if i + 1 == n else None
        if t == 2:                        # tail: B R2 '=' \s? '='
            if last not in _B64_R2:
                return None
            i += 1
            if i < n and value[i] in _WSSET:
                i += 1
            return True if i < n and value[i] == "=" and i + 1 == n else None
        return None

# Deliberately fragile shim: it applies ONLY to arelle-release 2.44.0 and ONLY
# while the original regex is byte-identical to the fingerprint recorded at gate
# time. If Arelle changes the code, this fails loudly instead of patching
# silently over an unreviewed upstream change.
_ARELLE_VERSION_EXPECTED = "2.44.0"
_ORIG_B64_PATTERN_SHA256 = "CB74F11E4811A3159BD37FD007E18820CAE658E3C1F8A60D5D3B79ED9DD5FDD9"

def _shim_selftest(orig):
    """Equivalence vs the ORIGINAL Arelle pattern object (regex module, V0
    semantics) on curated + deterministic fuzz inputs, plus a large payload that
    must complete in linear time. Raises on any divergence."""
    shim = _LinearBase64()
    cases = ["", "QUJD", "QQ==", "QUE=", "QUJD\nRUZH IEla", "QUJD RA==\t",
             "QUJ=", "QQ=Q", "QUJDRA==", "QUJDQQ", "QUJ D", "====", "A===",
             "TWFuTWFu", "QUJD-EFH", "QQ= =", "QUE =", "QU  JD", " Q",
             "AB==", "ABC =", "QUJD= ", "QUJD ", "QUJD\n", "QUJD\n\n",
             "QUJD \n", "QUJ D ", "QUE= ", "QUE=\n", "QQ== ", "QQ==\n",
             "QUJD QUJD", "QUJD  QUJD", "QQ = =", "Q Q==", "QUJD\nQUJD",
             "\n", " ", "QUJD\r\n", "QUE=\n\n"]
    for c in cases:
        want = orig.match(c) is not None
        got = shim.match(c) is not None
        if want != got:
            raise RuntimeError(f"shim divergence on {c!r}: orig={want} shim={got}")
    import random
    rng = random.Random(20260916)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/= \t\n\r-"
    fuzz = 0
    for _ in range(4000):
        c = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
        want = orig.match(c) is not None
        got = shim.match(c) is not None
        if want != got:
            raise RuntimeError(f"shim divergence on fuzz {c!r}: orig={want} shim={got}")
        fuzz += 1
    big = base64.b64encode(b"\xab" * (9 * 1024 * 1024)).decode("ascii")  # ~12 MB
    t0 = time.time()
    if shim.match(big) is not True:
        raise RuntimeError("shim rejected a valid large base64 payload")
    if time.time() - t0 > 5:
        raise RuntimeError("shim is not linear-time on a 12 MB payload")
    return {"cases": len(cases), "fuzz_cases": fuzz, "large_payload_bytes": len(big)}

def _install_base64_lexical_shim():
    from arelle import Version
    import inspect
    if getattr(Version, "version", None) != _ARELLE_VERSION_EXPECTED:
        raise RuntimeError(
            f"base64 shim gated to arelle-release=={_ARELLE_VERSION_EXPECTED}, "
            f"found {getattr(Version, 'version', '?')} - re-validate before running")
    orig = _XV.lexicalPatterns.get("base64Binary")
    fp = hashlib.sha256(getattr(orig, "pattern", "").encode("utf-8")).hexdigest().upper()
    if fp != _ORIG_B64_PATTERN_SHA256:
        raise RuntimeError(
            f"lexicalPatterns['base64Binary'] fingerprint {fp} != expected "
            f"{_ORIG_B64_PATTERN_SHA256} - upstream changed, shim NOT applied")
    selftest = _shim_selftest(orig)
    _XV.lexicalPatterns["base64Binary"] = _LinearBase64()
    return {
        "type": "base64Binary",
        "arelle_version_gated": _ARELLE_VERSION_EXPECTED,
        "orig_pattern_sha256": _ORIG_B64_PATTERN_SHA256,
        "shim_source_sha256": hashlib.sha256(
            inspect.getsource(_LinearBase64).encode("utf-8")).hexdigest().upper(),
        "selftest": selftest,
    }

XV_LEXICAL_SHIM = _install_base64_lexical_shim()

REPO = Path(__file__).resolve().parents[2]
R07 = REPO / "g0-r/R07-raw-retrieval/evidence"
R10 = REPO / "g0-r/R10-taxonomy-pinning/evidence"
EV = Path(__file__).resolve().parent / "evidence"
EV.mkdir(exist_ok=True)
TMP = EV / "_entrypoints"
TMP.mkdir(exist_ok=True)

IPP_PKG = R10 / "cnmv-ipp-2019-01-01-opencnmv-pkg.zip"
MODEL = {"SAN": "ipp_en", "BBVA": "ipp_en", "IBE": "ipp_ge"}
FILINGS = [
    (f"{iss}-H{h}-{yr}", f"ipp-{iss}-{'I' if h == 1 else 'II'}-semestre-de-{yr}.zip", iss, f"H{h}")
    for iss in ("SAN", "BBVA", "IBE")
    for h, yr in ((1, 2024), (2, 2024), (1, 2025), (2, 2025), (1, 2026))
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

def run_filing(fid, zipname, iss, semester):
    t0 = time.time()
    src = R07 / zipname
    src_sha = sha256_file(src)
    # entrypoint copy: raw artefact is preserved unmodified; the .zip suffix on
    # these XML instances would make Arelle treat the file as an archive
    entry = TMP / f"{fid}.xbrl"
    shutil.copyfile(src, entry)
    assert sha256_file(entry) == src_sha, "entrypoint copy diverged from raw artefact"
    oim_path = EV / f"{fid}.oim.json"
    opts = RuntimeOptions(
        entrypointFile=str(entry),
        internetConnectivity="offline",
        packages=[str(IPP_PKG)],
        plugins="saveLoadableOIM",
        validate=True,
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

    try:
        with Session() as s:
            run_ok = s.run(opts, logHandler=_H())
            models = s.get_models()
            log_path.write_text(json.dumps(log_msgs, indent=1, ensure_ascii=False), encoding="utf-8")
            if not models:
                return {"filing": fid, "status": "FAIL", "reason": "no model loaded"}
            m = models[0]

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
            docs = dts_docs(m)
            doc_objs, _seen2, _stk = [], set(), [m.modelDocument]
            while _stk:
                d = _stk.pop()
                if id(d) in _seen2:
                    continue
                _seen2.add(id(d))
                doc_objs.append(d)
                _stk.extend(getattr(d, "referencesDocument", {}).keys())
            dts_detail = []
            for d in doc_objs:
                fp = str(getattr(d, "filepath", "") or "")
                if "opencnmv-pkg.zip" in fp:
                    src_kind = "taxonomy_package"
                elif "arelle" in fp.lower() and "cache" in fp.lower() and "site-packages" in fp.lower():
                    src_kind = "arelle_builtin_cache"
                elif "arelle" in fp.lower() and "cache" in fp.lower():
                    src_kind = "arelle_user_cache"
                else:
                    src_kind = "local_input"
                dts_detail.append({"uri": getattr(d, "uri", ""), "resolved_from": src_kind})
            dts_detail.sort(key=lambda r: r["uri"])

            summary = {
                "filing": fid,
                "issuer": iss,
                "semester": semester,
                "model": MODEL[iss],
                "artifact": zipname,
                "artifact_sha256": src_sha,
                "arelle_version": arelle.__version__ if hasattr(arelle, "__version__") else "2.44.0",
                "runtime": {
                    "internetConnectivity": "offline",
                    "plugins": "saveLoadableOIM",
                    "validate": True,
                    "taxonomy_packages": [IPP_PKG.name],
                    "lexical_shim": XV_LEXICAL_SHIM,
                    "entrypoint_note": "raw artefact is XML stored with .zip suffix; "
                        "Arelle treats .zip as archive - fed via sha256-verified .xbrl copy",
                },
                "run_ok": run_ok,
                "elapsed_s": round(time.time() - t0, 1),
                "counts": {
                    "facts": len(records),
                    "contexts": len(m.contexts),
                    "units": len(m.units),
                    "concepts": len(m.qnameConcepts),
                    "dts_documents": len(docs),
                    "fact_footnote_relationships": footnote_rels,
                    "nil_facts": nil_facts,
                    "contexts_explicit_dims": explicit_dims,
                    "contexts_typed_dims": typed_dims,
                    "fact_languages": langs,
                },
                "concept_namespaces": dict(ns_domains),
                "log_code_counts": dict(codes),
                "dts_resolution": dts_detail,
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
                diff = list((api_keys - oim_keys).items())[:10] + [("OIM-ONLY", k) for k, v in list((oim_keys - api_keys).items())[:10]]
                ctrl["multiset_diff_sample"] = [str(d)[:300] for d in diff]
                summary["control_A"] = ctrl
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
    finally:
        entry.unlink(missing_ok=True)

def main():
    sel = sys.argv[1] if len(sys.argv) > 1 else "all"
    results = []
    for fid, zipname, iss, semester in FILINGS:
        if sel != "all" and fid != sel:
            continue
        print(f"=== {fid} ({MODEL[iss]}) ===", flush=True)
        s = run_filing(fid, zipname, iss, semester)
        results.append(s)
        if "counts" in s:
            c = s["counts"]
            print(f"  facts={c['facts']} contexts={c['contexts']} units={c['units']} "
                  f"concepts={c['concepts']} dts={c['dts_documents']} ioerr={s['offline_evidence']['io_errors']} "
                  f"ctrlA={s.get('control_A', {}).get('fact_multiset_equal')}", flush=True)
    out = EV / "r12_results.json"
    prev = {r["filing"]: r for r in json.loads(out.read_text(encoding="utf-8"))} if out.exists() else {}
    prev.update({r["filing"]: r for r in results})
    merged = [prev[fid] for fid, _, _, _ in FILINGS if fid in prev]
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", out)

if __name__ == "__main__":
    main()
