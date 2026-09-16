# G1-D — full capture of the falsification candidate:
#   TELEFONICA, S.A.  FY2024  registro(nregaud)=20484  (dual-variant signal,
#   1 substitution event found by g1d_scan2).
#
# Captures: result rows es/en (tokens, cells), infadicionifa es/en (all
# event docs preserved), both variant packages (sha256 + internal zip
# timestamps), and extracts certificate text looking for any reference to
# language / variant / individual-vs-consolidated scope. Then classifies:
#   BOTH_VARIANTS_REPLACED | ES_ONLY_REPLACED | EN_ONLY_REPLACED |
#   VARIANT_SCOPE_NOT_OBSERVABLE
from __future__ import annotations

import hashlib, io, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"

BASE = "https://www.cnmv.es"
SEARCH = BASE + "/Portal/consultas/busqueda?id=25&lang={lang}"
INFAD = BASE + "/portal/consultas/ifa/infadicionifa?id=0&lang={lang}&nreg={nreg}&nregaud={nregaud}"
VERDOC = BASE + "/webservices/verdocumento/ver?e={tok}"
UA = {"User-Agent": "OpenCNMV-G1D/1.0 (evidence probe)"}

ISS = {"denom": "TELEFONICA", "nregaud": "20484"}


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def hidden_fields(html):
    f = {}
    for m in re.finditer(r"<input[^>]*>", html):
        tag = m.group(0)
        n = re.search(r'name="([^"]*)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n and ("VIEWSTATE" in n.group(1) or "EVENT" in n.group(1)):
            f[n.group(1)] = v.group(1) if v else ""
    return f


def search_rows(s, denom, lang, desde, hasta):
    url = SEARCH.format(lang=lang)
    r = s.get(url, timeout=60)
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


def all_rows(html):
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
        if cells and cells[0].isdigit():
            toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", m.group(1))
            inf = re.findall(r"infadicionifa[^\"']+", m.group(1))
            rows.append({"cells": cells,
                         "tokens": [t.replace("&amp;", "&") for t in toks],
                         "infadicion": [i.replace("&amp;", "&")
                                        for i in inf]})
    return rows


def event_rows(html):
    out = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
        toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", m.group(1))
        if cells and re.match(r"\d{2}/\d{2}/\d{4}", cells[0]):
            out.append({"cells": cells,
                        "tokens": [t.replace("&amp;", "&") for t in toks]})
    return out


def pkg_lang_tag(z):
    for rt in {n.split("/")[0] for n in z.namelist() if "/" in n}:
        mm = re.search(r"-(es|en)$", rt)
        if mm:
            return mm.group(1)
    return "?"


def main():
    s = requests.Session()
    s.headers.update(UA)
    man = {"probe": "G1-D TEF-20484 lifecycle capture",
           "executed_at": datetime.now(timezone.utc).isoformat(),
           "artifacts": []}
    res = {"issuer": "TELEFONICA", "nregaud": ISS["nregaud"],
           "phase1": {}, "phase2": {}, "phase3": {}}
    nreg = None

    # ---- phase 1: rows + packages per lang -----------------------------
    for lang in ("es", "en"):
        html = search_rows(s, ISS["denom"], lang, "2024-01-01", "2026-12-31")
        raw = html.encode("utf-8")
        (EV / f"busqueda25-TELEFONICA-{lang}.html").write_bytes(raw)
        man["artifacts"].append({"file": f"evidence/busqueda25-TELEFONICA-{lang}.html",
                                 "sha256": sha256(raw),
                                 "bytes": len(raw),
                                 "kind": "SEARCH_RESULTS_PAGE",
                                 "source_url": SEARCH.format(lang=lang)})
        row = next((r for r in all_rows(html)
                    if r["cells"][0] == ISS["nregaud"]), None)
        v = {"row": row}
        if row and row["tokens"]:
            if nreg is None and row["infadicion"]:
                mm = re.search(r"nreg=(\d+)", row["infadicion"][0])
                nreg = mm.group(1) if mm else None
            for i, tok in enumerate(row["tokens"]):
                r = s.get(VERDOC.format(tok=tok), timeout=600)
                body = r.content
                kind = ("ESEF_PACKAGE_ZIP" if body[:2] == b"PK" else
                        "DOC_XHTML" if b"html" in body[:500].lower() else
                        "DOC_PDF" if body[:4] == b"%PDF" else "DOC_OTHER")
                rec = {"token_idx": i, "sha256": sha256(body),
                       "bytes": len(body), "kind": kind,
                       "ctype": r.headers.get("Content-Type", "")}
                if kind == "ESEF_PACKAGE_ZIP":
                    z = zipfile.ZipFile(io.BytesIO(body))
                    rec["package_lang_tag"] = pkg_lang_tag(z)
                    rec["zip_member_dt_distinct"] = sorted(
                        {str(i_.date_time) for i_ in z.infolist()
                         if not i_.is_dir()})
                    fn = f"pkg-TEF-20484-{lang}-{rec['sha256'][:12]}.zip"
                    (EV / fn).write_bytes(body)
                    man["artifacts"].append(
                        {"file": f"evidence/{fn}", "sha256": rec["sha256"],
                         "bytes": len(body), "kind": kind, "ui_lang": lang,
                         "source_url": VERDOC.format(tok=tok)})
                else:
                    # keep a prefix for viewer evidence
                    fn = f"doc-TEF-20484-{lang}-{i}.prefix"
                    (EV / fn).write_bytes(body[:262144])
                    man["artifacts"].append(
                        {"file": f"evidence/{fn}",
                         "sha256": sha256(body[:262144]),
                         "bytes": len(body[:262144]),
                         "kind": kind + "_PREFIX", "ui_lang": lang,
                         "source_url": VERDOC.format(tok=tok)})
                v.setdefault("docs", []).append(rec)
        res["phase1"][lang] = v
        print("phase1", lang, "docs:", [(d["kind"], d["sha256"][:12])
                                       for d in v.get("docs", [])],
              flush=True)
    res["nreg"] = nreg

    es_pkg = [d for d in res["phase1"]["es"].get("docs", [])
              if d["kind"] == "ESEF_PACKAGE_ZIP"]
    en_pkg = [d for d in res["phase1"]["en"].get("docs", [])
              if d["kind"] == "ESEF_PACKAGE_ZIP"]
    es_tag = es_pkg[0]["package_lang_tag"] if es_pkg else None
    en_tag = en_pkg[0]["package_lang_tag"] if en_pkg else None
    variants = sorted({t for t in (es_tag, en_tag) if t in ("es", "en")})
    res["submitted_variants"] = variants
    res["submitted_variant_count"] = len(variants)
    res["verdict_p1"] = ("DUAL_VARIANT_SHARED_REGISTRY" if len(variants) == 2
                         else "SINGLE_VARIANT_WITH_UI_FALLBACK"
                         if variants == ["es"] else "UNRESOLVED")
    print("verdict_p1:", res["verdict_p1"], "| tags:", es_tag, "/", en_tag)

    # ---- phase 2: infadicionifa both langs + event docs ----------------
    per_lang = {}
    for lang in ("es", "en"):
        url = INFAD.format(lang=lang, nreg=nreg, nregaud=ISS["nregaud"])
        r = s.get(url, timeout=60)
        (EV / f"infadicionifa-TELEFONICA-{lang}.html").write_bytes(r.content)
        man["artifacts"].append(
            {"file": f"evidence/infadicionifa-TELEFONICA-{lang}.html",
             "sha256": sha256(r.content), "bytes": len(r.content),
             "kind": "INFADICIONIFA_PAGE", "source_url": url})
        evs = event_rows(r.text)
        docs = []
        for i, e in enumerate(evs):
            for j, tok in enumerate(e["tokens"]):
                rr = s.get(VERDOC.format(tok=tok), timeout=300)
                body = rr.content
                ext = ".pdf" if body[:4] == b"%PDF" else ".bin"
                fn = f"doc-TEF-20484-{lang}-e{i}-{j}{ext}"
                (EV / fn).write_bytes(body)
                txt = ""
                if ext == ".pdf":
                    try:
                        from pypdf import PdfReader
                        txt = "\n".join((p.extract_text() or "")
                                        for p in PdfReader(io.BytesIO(body)).pages)
                    except Exception as ex:  # noqa: BLE001
                        txt = f"<pdf fail: {ex}>"
                (EV / f"doc-TEF-20484-{lang}-e{i}-{j}.txt").write_text(
                    txt, encoding="utf-8")
                man["artifacts"].append(
                    {"file": f"evidence/{fn}", "sha256": sha256(body),
                     "bytes": len(body), "kind": "EVENT_DOCUMENT",
                     "ui_lang": lang, "event_row": e["cells"],
                     "source_url": VERDOC.format(tok=tok)})
                docs.append({"file": fn, "sha256": sha256(body),
                             "event": e["cells"]})
        per_lang[lang] = {"events": evs, "docs": docs}
    res["phase2"] = per_lang
    for lang in ("es", "en"):
        print("phase2", lang, "events:",
              [(e["cells"][0], e["cells"][1][:60] if len(e["cells"]) > 1 else "")
               for e in per_lang[lang]["events"]], flush=True)

    # ---- phase 3: scope analysis ---------------------------------------
    # (a) do en/es event rows differ?  (b) do the served certificates differ?
    # (c) does cert text reference language / document scope?
    es_ev = per_lang["es"]["events"]
    en_ev = per_lang["en"]["events"]
    same_events = [e["cells"] for e in es_ev] == [e["cells"] for e in en_ev]
    doc_pairs = {}
    for i, d in enumerate(per_lang["es"]["docs"]):
        other = per_lang["en"]["docs"]
        doc_pairs[d["file"]] = (other[i]["sha256"] == d["sha256"]
                                if i < len(other) else None)
    scope_signals = []
    for d in per_lang["es"]["docs"] + per_lang["en"]["docs"]:
        txt = (EV / (d["file"].rsplit(".", 1)[0] + ".txt")).read_text(
            encoding="utf-8")
        for pat in (r"(?i)ingl[eé]s", r"(?i)english", r"(?i)castellan",
                    r"(?i)spanish", r"(?i)idioma", r"(?i)language",
                    r"(?i)individual", r"(?i)consolidad",
                    r"(?i)fichero[^.]{0,80}", r"(?i)archivo[^.]{0,80}",
                    r"(?i)sustitu\w+[^.]{0,120}"):
            for mm in re.finditer(pat, txt):
                scope_signals.append({"doc": d["file"],
                                      "match": mm.group(0)[:160]})
    res["phase3"] = {"event_rows_equal_across_langs": same_events,
                     "event_doc_bytes_equal_es_vs_en": doc_pairs,
                     "scope_signals": scope_signals}
    (HERE / "g1d_tef20484.json").write_bytes(json.dumps(
        res, indent=1, ensure_ascii=False).encode("utf-8"))
    man["artifacts"].append({"file": "g1d_tef20484.json",
                             "sha256": sha256(
                                 (HERE / "g1d_tef20484.json").read_bytes()),
                             "bytes": (HERE / "g1d_tef20484.json").stat().st_size,
                             "kind": "ANALYSIS"})
    mpath = HERE / "manifest.json"
    old = json.loads(mpath.read_text(encoding="utf-8")) \
        if mpath.exists() else {"artifacts": []}
    old["artifacts"].extend(man["artifacts"])
    old["executed_at"] = man["executed_at"]
    mpath.write_bytes(json.dumps(old, indent=1, ensure_ascii=False)
                      .encode("utf-8"))
    print("\n=== phase3 ===")
    print("event rows equal es/en:", same_events)
    print("doc bytes equal es/en:", doc_pairs)
    for s_ in scope_signals[:20]:
        print("  signal:", s_["doc"], "->", s_["match"][:110])
    print("wrote g1d_tef20484.json")


if __name__ == "__main__":
    main()
