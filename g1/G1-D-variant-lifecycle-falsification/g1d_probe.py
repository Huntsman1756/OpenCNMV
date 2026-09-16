# G1-D — VARIANT_LIFECYCLE_FALSIFICATION probe.
#
# Question: can a version_event (Circular 3/2018 substitution) affect a
# SUBSET of submission_variants, or does a registry substitution always
# replace the whole artifact set?
#
# Out-of-corpus falsification fixtures (filings with observed substitutions,
# provided by the user from official CNMV surfaces):
#   AMPER      FY2025  nreg=2026031562 nregaud=20938  (TWO substitution
#                        certificates dated 04/03/2026; en surface exists)
#   BANKINTER  FY2025  nreg=2026026888 nregaud=20860  (substitution
#                        24/02/2026)
#   URBAR      FY2025  discovered via busqueda?id=25  (substitution
#                        18/06/2026)
#
# Phases:
#   1. classify each filing via the G1-A mechanism:
#        DUAL_VARIANT_SHARED_REGISTRY vs SINGLE_VARIANT_WITH_UI_FALLBACK
#      (busqueda?id=25 in lang=es/lang=en; ZIP package tag per view)
#   2. for each filing, capture infadicionifa in both UI languages,
#      preserve every event-row document (substitution certificates), and
#      record ZIP internal member timestamps (which artifact set was
#      re-uploaded can leave traces in zip metadata).
#   3. deterministic extraction of any language/scope reference in the
#      preserved certificate bytes (pypdf text), then classify:
#        BOTH_VARIANTS_REPLACED | ES_ONLY_REPLACED | EN_ONLY_REPLACED |
#        VARIANT_SCOPE_NOT_OBSERVABLE
#      BOTH is never inferred from a shared registry date alone.
from __future__ import annotations

import hashlib, io, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"
EV.mkdir(exist_ok=True)

BASE = "https://www.cnmv.es"
SEARCH = BASE + "/Portal/consultas/busqueda?id=25&lang={lang}"
INFAD = BASE + "/portal/consultas/ifa/infadicionifa?id=0&lang={lang}&nreg={nreg}&nregaud={nregaud}"
VERDOC = BASE + "/webservices/verdocumento/ver?e={tok}"
UA = {"User-Agent": "OpenCNMV-G1D/1.0 (evidence probe)"}

# expected substitution dates observed by the user on official pages
CANDIDATES = [
    {"issuer": "AMPER", "denom": "AMPER", "nif": "A-28079226",
     "nregaud": "20938", "nreg": "2026031562",
     "expected_substitutions": ["04/03/2026"]},
    {"issuer": "BANKINTER", "denom": "BANKINTER", "nif": None,
     "nregaud": "20860", "nreg": "2026026888",
     "expected_substitutions": ["24/02/2026"]},
    {"issuer": "URBAR", "denom": "URBAR", "nif": None,
     "nregaud": None, "nreg": None,
     "expected_substitutions": ["18/06/2026"]},
]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def hidden_fields(html: str) -> dict:
    f = {}
    for m in re.finditer(r"<input[^>]*>", html):
        tag = m.group(0)
        n = re.search(r'name="([^"]*)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n and ("VIEWSTATE" in n.group(1) or "EVENT" in n.group(1)):
            f[n.group(1)] = v.group(1) if v else ""
    return f


def search_ifa(s, denom, lang, desde, hasta):
    url = SEARCH.format(lang=lang)
    r = s.get(url, timeout=60)
    r.raise_for_status()
    data = {**hidden_fields(r.text),
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": denom,
            "ctl00$ContentPrincipal$wFechas$fecha_desde": desde,
            "ctl00$ContentPrincipal$wFechas$fecha_hasta": hasta,
            "ctl00$ContentPrincipal$wFechas$ult_dias": "",
            "ctl00$ContentPrincipal$btnOk":
                "Search" if lang == "en" else "Buscar"}
    r2 = s.post(url, data=data, timeout=180, headers={"Referer": url})
    r2.raise_for_status()
    return r2.text


def all_rows(html: str):
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip() for t in tds]
        if cells and cells[0].isdigit():
            toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", row)
            inf = re.findall(r"infadicionifa[^\"']+", row)
            rows.append({"cells": cells,
                         "tokens": [t.replace("&amp;", "&") for t in toks],
                         "infadicion": [i.replace("&amp;", "&") for i in inf]})
    return rows


def row_for(html, registro):
    for r in all_rows(html):
        if r["cells"][0] == registro:
            return r
    return None


def fetch_doc(s, token):
    r = s.get(VERDOC.format(tok=token), timeout=600)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "")


def pkg_lang_tag(body: bytes):
    if body[:2] != b"PK":
        return None, None
    z = zipfile.ZipFile(io.BytesIO(body))
    roots = {n.split("/")[0] for n in z.namelist() if "/" in n}
    for rt in roots:
        m = re.search(r"-(es|en)$", rt)
        if m:
            return m.group(1), z
    return "?", z


def pdf_text(body: bytes) -> str:
    try:
        from pypdf import PdfReader
        rd = PdfReader(io.BytesIO(body))
        return "\n".join((p.extract_text() or "") for p in rd.pages)
    except Exception as e:  # noqa: BLE001
        return f"<pdf extraction failed: {e}>"


def event_rows(html: str):
    """infadicionifa event table: date + description + doc tokens."""
    out = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip() for t in tds]
        toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", row)
        if cells and re.match(r"\d{2}/\d{2}/\d{4}", cells[0]):
            out.append({"cells": cells,
                        "tokens": [t.replace("&amp;", "&") for t in toks]})
    return out


def main():
    s = requests.Session()
    s.headers.update(UA)
    manifest = {"probe": "G1-D VARIANT_LIFECYCLE_FALSIFICATION",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "artifacts": []}
    results = []

    for cand in CANDIDATES:
        iss = cand["issuer"]
        res = {"issuer": iss, "phase1": {}, "phase2": {}, "phase3": {}}

        # ---------- PHASE 1: variant classification --------------------
        for lang in ("es", "en"):
            html = search_ifa(s, cand["denom"], lang, "2025-01-01",
                              "2026-12-31")
            fn = f"busqueda25-{iss}-{lang}.html"
            raw = html.encode("utf-8")
            (EV / fn).write_bytes(raw)
            manifest["artifacts"].append(
                {"file": f"evidence/{fn}", "sha256": sha256(raw),
                 "bytes": len(raw), "kind": "SEARCH_RESULTS_PAGE",
                 "source_url": SEARCH.format(lang=lang)
                 + f" [POST denom={cand['denom']}]"})
            rows = all_rows(html)
            # target row: known nregaud, else latest registro (URBAR)
            row = row_for(html, cand["nregaud"]) if cand["nregaud"] else \
                (max(rows, key=lambda r: int(r["cells"][0])) if rows else None)
            vres = {"ui_lang": lang, "n_rows": len(rows)}
            if row:
                vres["row"] = row
                if not cand["nregaud"]:
                    cand["nregaud"] = row["cells"][0]
                    mm = re.search(r"nreg=(\d+)", row["infadicion"][0]) \
                        if row["infadicion"] else None
                    if mm:
                        cand["nreg"] = mm.group(1)
                if row["tokens"]:
                    body, ctype = fetch_doc(s, row["tokens"][-1])
                    tag, z = pkg_lang_tag(body)
                    vres["zip_sha256"] = sha256(body)
                    vres["zip_bytes"] = len(body)
                    vres["zip_content_type"] = ctype
                    vres["package_lang_tag"] = tag
                    if z:
                        members = [i for i in z.infolist()
                                   if not i.is_dir()]
                        vres["zip_member_dt_min"] = min(
                            str(i.date_time) for i in members)
                        vres["zip_member_dt_max"] = max(
                            str(i.date_time) for i in members)
                        vres["zip_member_dt_distinct"] = sorted(
                            {str(i.date_time) for i in members})[:5]
                        fn2 = f"pkg-{iss}-{tag}-{vres['zip_sha256'][:12]}.zip"
                        (EV / fn2).write_bytes(body)
                        manifest["artifacts"].append(
                            {"file": f"evidence/{fn2}",
                             "sha256": vres["zip_sha256"],
                             "bytes": len(body),
                             "kind": "ESEF_PACKAGE_ZIP",
                             "ui_lang": lang,
                             "source_url": VERDOC.format(
                                 tok=row["tokens"][-1])
                             + f" (busqueda lang={lang}, "
                               f"registro {row['cells'][0]})"})
            res["phase1"][lang] = vres

        es_t = res["phase1"]["es"].get("package_lang_tag")
        en_t = res["phase1"]["en"].get("package_lang_tag")
        variants = sorted({t for t in (es_t, en_t) if t in ("es", "en")})
        res["nregaud"] = cand["nregaud"]
        res["nreg"] = cand["nreg"]
        res["submitted_variants"] = variants
        res["submitted_variant_count"] = len(variants)
        res["verdict_p1"] = ("DUAL_VARIANT_SHARED_REGISTRY"
                             if len(variants) == 2
                             else "SINGLE_VARIANT_WITH_UI_FALLBACK"
                             if variants == ["es"] else "UNRESOLVED")
        print(iss, "phase1:", res["verdict_p1"],
              "| es tag:", es_t, "| en tag:", en_t, flush=True)

        # ---------- PHASE 2: infadicionifa + substitution docs ---------
        if not cand["nregaud"] or not cand["nreg"]:
            res["phase2"]["skip"] = "missing nreg/nregaud"
            results.append(res)
            continue
        per_lang = {}
        for lang in ("es", "en"):
            url = INFAD.format(lang=lang, nreg=cand["nreg"],
                               nregaud=cand["nregaud"])
            r = s.get(url, timeout=60)
            r.raise_for_status()
            fn = f"infadicionifa-{iss}-{lang}.html"
            (EV / fn).write_bytes(r.content)
            manifest["artifacts"].append(
                {"file": f"evidence/{fn}", "sha256": sha256(r.content),
                 "bytes": len(r.content), "kind": "INFADICIONIFA_PAGE",
                 "source_url": url})
            evs = event_rows(r.text)
            docs = []
            for i, e in enumerate(evs):
                for j, tok in enumerate(e["tokens"]):
                    body, ctype = fetch_doc(s, tok)
                    ext = ".pdf" if body[:4] == b"%PDF" else ".bin"
                    fn3 = f"doc-{iss}-{lang}-e{i}-{j}{ext}"
                    (EV / fn3).write_bytes(body)
                    manifest["artifacts"].append(
                        {"file": f"evidence/{fn3}", "sha256": sha256(body),
                         "bytes": len(body), "kind": "EVENT_DOCUMENT",
                         "ui_lang": lang, "event_row": e["cells"],
                         "source_url": VERDOC.format(tok=tok)})
                    docs.append({"file": fn3, "sha256": sha256(body),
                                 "ctype": ctype, "event": e["cells"]})
            per_lang[lang] = {"events": evs, "docs": docs}
        res["phase2"] = per_lang
        print(iss, "phase2: es events", len(per_lang["es"]["events"]),
              "| en events", len(per_lang["en"]["events"]), flush=True)
        results.append(res)

    out = {"results": results}
    (HERE / "g1d_capture.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    manifest["artifacts"].append(
        {"file": "g1d_capture.json",
         "sha256": sha256((HERE / "g1d_capture.json").read_bytes()),
         "bytes": (HERE / "g1d_capture.json").stat().st_size,
         "kind": "CAPTURE_MATRIX"})
    (HERE / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote g1d_capture.json + manifest.json")


if __name__ == "__main__":
    main()
