"""Fact canonicalization — structural key vs payload (I5/I6).

fact_key:    concept | entity | period | dimensions | unit | language
payload:     value, decimals, isNil, value_sha256

No dedup by concept+period: entity/period/dimensions/unit/language are all
part of identity (R17 falsified the naive key empirically).
"""
from __future__ import annotations

import hashlib, json


def fact_key(concept: str, entity: str, period: str,
             dimensions: dict | None = None, unit: str | None = None,
             language: str | None = None) -> dict:
    return {"concept": concept, "entity": entity, "period": period,
            "dimensions": dimensions or {}, "unit": unit,
            "language": language}


def fact_payload(value: str | None, xvalue: str | None = None,
                 decimals: str | None = None, is_nil: bool = False) -> dict:
    return {"value": value, "xvalue": xvalue, "decimals": decimals,
            "is_nil": is_nil,
            "value_sha256": hashlib.sha256((value or "").encode("utf-8"))
            .hexdigest()}


def fact_id(key: dict, variant_version_id: str) -> str:
    canonical = "|".join([
        key["concept"], key["entity"], key["period"],
        ";".join(f"{k}={v}" for k, v in sorted(key["dimensions"].items())),
        key["unit"] or "", key["language"] or ""])
    return "fact:" + hashlib.sha256(
        f"{variant_version_id}|{canonical}".encode("utf-8")).hexdigest()


# --- fact records from a loaded Arelle model --------------------------------
#
# fact_record() converts an arelle ModelFact into a canonical record. The
# record preserves COMPLETE unit semantics (numerator and denominator, all
# measures, sorted), explicit AND typed dimensions, decimals, nil, xml:lang
# and the raw value hash — nothing is projected away.
#
# Two record profiles reproduce the frozen oracle serialisations exactly:
#   "esef"  -> G1-B field set (adds concept_type, is_numeric, value_full,
#              xValue_full, ns_kind)
#   "ipp"   -> R12 field set
# Serialise with json.dumps(sort_keys=True) + "\n" for byte-stable output.

def qn(q) -> str:
    return f"{q.namespaceURI}#{q.localName}"


def dim_repr(dim) -> str:
    if getattr(dim, "isExplicit", False):
        return "E:" + (qn(dim.memberQname) if dim.memberQname is not None else "nil")
    tv = getattr(dim, "typedMember", None)
    return "T:" + (tv.stringValue if tv is not None and hasattr(tv, "stringValue")
                   else str(tv))


def unit_sig(unit) -> str:
    """Complete unit signature: ALL numerator measures, then ALL denominator
    measures (each sorted). A bare numerator-first-measure would silently
    collapse distinct units — forbidden."""
    if unit is None:
        return ""
    num, den = unit.measures
    s = "*".join(sorted(qn(q) for q in num))
    if den:
        s += "/" + "*".join(sorted(qn(q) for q in den))
    return s


def ctx_sig(ctx) -> str:
    scheme, ident = ctx.entityIdentifier
    if ctx.isStartEndPeriod:
        period = f"{ctx.startDatetime.date()}/{ctx.endDatetime.date()}"
    elif ctx.isInstantPeriod:
        period = str(ctx.instantDatetime.date())
    else:
        period = "forever"
    dims = ";".join(f"{qn(d)}={dim_repr(v)}"
                    for d, v in sorted(ctx.qnameDims.items(), key=lambda kv: qn(kv[0])))
    return f"{scheme}|{ident}|{period}|{dims}"


def _val(v: str | None, keep_full: bool):
    if v is None:
        return (None, 0, None, None) if keep_full else (None, 0, None)
    b = v.encode("utf-8")
    out = (hashlib.sha256(b).hexdigest().upper(), len(b), v[:300])
    if keep_full:
        return out + (v if len(b) <= 512 else None,)
    return out


def fact_record(f, profile: str = "esef", ext_ns: set | None = None) -> dict:
    ctx = f.context
    full = profile == "esef"
    v_sha, v_len, v_prev, *vf = _val(f.value, full)
    xv = str(f.xValue) if not f.isNil else None
    xv_sha, xv_len, xv_prev, *xf = _val(xv, full)
    rec = {
        "concept": qn(f.qname),
        "value_sha256": v_sha,
        "value_len": v_len,
        "value_preview": v_prev,
        "xValue_sha256": xv_sha,
        "xValue_len": xv_len,
        # frozen profiles differ: ESEF keeps a 300-char xValue preview
        # unconditionally; IPP only when the xValue is short (<2000)
        "xValue_preview": (xv_prev if profile == "esef"
                           else (xv_prev if xv_len and xv_len < 2000 else None)),
        "isNil": bool(f.isNil),
        "decimals": str(f.decimals) if f.decimals is not None else None,
        "contextID": f.contextID,
        "unitID": f.unitID,
        "lang": f.xmlLang,
    }
    if full:
        rec["concept_type"] = (qn(f.concept.typeQname)
                               if getattr(f, "concept", None) is not None
                               and getattr(f.concept, "typeQname", None) is not None
                               else None)
        rec["is_numeric"] = bool(getattr(f, "isNumeric", False))
        rec["value_full"] = vf[0]
        rec["xValue_full"] = xf[0]
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
    if full and ext_ns is not None:
        ns = rec["concept"].rsplit("#", 1)[0]
        rec["ns_kind"] = "issuer_extension" if ns in ext_ns else "taxonomy"
    return rec


def fact_sort_key(rec: dict) -> str:
    return "|".join([
        rec["concept"], rec.get("entity_scheme") or "", rec.get("entity") or "",
        rec.get("period_start") or "", rec.get("period_end") or "",
        rec.get("period_instant") or "", "1" if rec.get("period_forever") else "",
        rec.get("unit") or "", (rec.get("lang") or "") if not rec.get("unit") else "",
        ";".join(f"{k}={v}" for k, v in sorted(rec.get("dimensions", {}).items())),
    ])


def facts_to_records(model, profile: str = "esef",
                     ext_ns: set | None = None) -> list[dict]:
    recs = [fact_record(f, profile=profile, ext_ns=ext_ns) for f in model.facts]
    recs.sort(key=fact_sort_key)
    return recs


# --- oracle / OIM comparison -------------------------------------------------

_CMP_FIELDS = ("concept", "entity_scheme", "entity", "period_start",
               "period_end", "period_instant", "period_forever", "unit",
               "decimals", "isNil", "lang", "value_sha256", "contextID",
               "unitID")


def comparison_key(rec: dict) -> tuple:
    dims = tuple(sorted((rec.get("dimensions") or {}).items()))
    return tuple(rec.get(k) for k in _CMP_FIELDS) + (dims,)


def fact_multiset(records) -> "Counter":
    from collections import Counter
    return Counter(comparison_key(r) for r in records)


_OIM_SKIP_DIM_KEYS = ("concept", "entity", "period", "unit", "language", "noteId")


def oim_fact_key(fact: dict, nsmap: dict) -> str:
    """Canonical fact key from an OIM (xBRL-JSON) fact — Control A.

    Mirrors the semantic identity of comparison_key(): full unit with
    numerator/denominator, explicit vs typed dimensions, period forms.
    """
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
        if k in _OIM_SKIP_DIM_KEYS:
            continue
        if isinstance(v, str) and ":" in v and resolve(v) != v:
            dims[resolve(k)] = "E:" + resolve(v)
        else:
            dims[resolve(k)] = "T:" + (v if isinstance(v, str)
                                       else json.dumps(v, sort_keys=True))
    return "|".join([concept, scheme, ident or "", ps, pe, inst, forever,
                     unit or "", d.get("language", "") if not unit else "",
                     ";".join(f"{k}={v}" for k, v in sorted(dims.items()))])


def api_key_for_oim(rec: dict) -> str:
    """The same canonical key shape as oim_fact_key, for an API-side record."""
    dims = rec.get("dimensions") or {}
    return "|".join([
        rec["concept"], rec.get("entity_scheme") or "", rec.get("entity") or "",
        rec.get("period_start") or "", rec.get("period_end") or "",
        rec.get("period_instant") or "", "1" if rec.get("period_forever") else "",
        rec.get("unit") or "", (rec.get("lang") or "") if not rec.get("unit") else "",
        ";".join(f"{k}={v}" for k, v in sorted(dims.items())),
    ])
