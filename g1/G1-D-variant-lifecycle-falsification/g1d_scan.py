# G1-D — discovery scan: find dual-variant filings WITH substitution events.
#
# For each issuer in the watchlist (large caps — the plausible -en filers):
#   1. busqueda?id=25 POST (es). If the response is an entity picker,
#      POST btnSeleccionar with the S.A. option.
#   2. locate the FY2025 row (period-end cell contains 31/12/2025).
#   3. fetch infadicionifa (es) and detect 'sustituci' event rows.
#   4. ZIP dual-variant signal WITHOUT full download: record whether the
#      lang=es and lang=en ZIP verdocumento tokens differ (IBE fallback had
#      identical tokens; dual filings have distinct tokens).
#
# Filings with a substitution event then go through the full capture in
# g1d_probe.py style. This scan never fabricates scope conclusions.
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
VERDOC = BASE + "/webservices/verdocumento/ver?e={tok}"
UA = {"User-Agent": "OpenCNMV-G1D/1.0 (evidence probe)"}

WATCHLIST = ["ACS", "ACCIONA", "ACERINOX", "AENA", "AMADEUS", "BANKINTER",
             "CAIXABANK", "CELLNEX", "INMOBILIARIA COLONIAL", "ENDESA",
             "ENAGAS", "FERROVIAL", "FLUIDRA", "GRIFOLS", "IAG", "IBERDROLA",
             "INDITEX", "INDRA", "LOGISTA", "MAPFRE", "MELIA",
             "MERLIN PROPERTIES", "NATURGY", "PUIG", "REDEIA", "REPSOL",
             "SABADELL", "BANCO SANTANDER", "TELEFONICA", "VISCOFAN",
             "EBRO FOODS", "SOLARIA", "AMPER", "URBAR", "OHLA",
             "PHARMA MAR", "ARCELORMITTAL"]


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


def post_search(s, url, extra, lang):
    data = {**extra,
            "ctl00$ContentPrincipal$wFechas$ult_dias": "",
            "ctl00$ContentPrincipal$btnOk":
                "Search" if lang == "en" else "Buscar"}
    r = s.post(url, data=data, timeout=180, headers={"Referer": url})
    r.raise_for_status()
    return r.text


def resolve_results(s, denom, lang):
    """Return results HTML, handling the entity-picker postback."""
    url = SEARCH.format(lang=lang)
    r = s.get(url, timeout=60)
    r.raise_for_status()
    hf = hidden_fields(r.text)
    data = {**hf,
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": denom,
            "ctl00$ContentPrincipal$wFechas$fecha_desde": "2025-01-01",
            "ctl00$ContentPrincipal$wFechas$fecha_hasta": "2026-12-31"}
    html = post_search(s, url, data, lang)
    # entity picker? -> select the S.A. option and post again
    if "lstSeleccion" in html and "btnSeleccionar" in html:
        opts = re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>',
                          html)
        pick = None
        for v, t in opts:
            if "S.A." in t.upper() or t.strip().upper().startswith("A"):
                pick = (v, t)
                break
        if pick is None and opts:
            pick = opts[-1]
        if pick:
            hf2 = hidden_fields(html)
            data2 = {**hf2,
                     "ctl00$ContentPrincipal$wbusqueda$lstSeleccion": pick[0],
                     "ctl00$ContentPrincipal$wbusqueda$btnSeleccionar":
                         "Seleccionar" if lang == "es" else "Select"}
            r2 = s.post(url, data=data2, timeout=180,
                        headers={"Referer": url})
            r2.raise_for_status()
            return r2.text, pick
    return html, None


def all_rows(html):
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if cells and cells[0].isdigit():
            toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", row)
            inf = re.findall(r"infadicionifa[^\"']+", row)
            rows.append({"cells": cells,
                         "tokens": [t.replace("&amp;", "&") for t in toks],
                         "infadicion": [i.replace("&amp;", "&")
                                        for i in inf]})
    return rows


def main():
    s = requests.Session()
    s.headers.update(UA)
    out = []
    for denom in WATCHLIST:
        rec = {"denom": denom}
        try:
            html_es, pick = resolve_results(s, denom, "es")
            rec["entity_pick"] = pick[1].strip() if pick else None
            rows = all_rows(html_es)
            fy25 = [r for r in rows if "31/12/2025" in (r["cells"][1]
                    if len(r["cells"]) > 1 else "")]
            if not fy25:
                fy25 = [max(rows, key=lambda r: int(r["cells"][0]))] \
                    if rows else []
            rec["row"] = fy25[0] if fy25 else None
            if not rec["row"]:
                rec["status"] = "NO_FY2025_ROW"
                out.append(rec)
                print(denom, "-> no row", flush=True)
                continue
            row = rec["row"]
            rec["registro"] = row["cells"][0]
            rec["pub_date"] = row["cells"][2] if len(row["cells"]) > 2 else None
            mm = re.search(r"nreg=(\d+)&(?:amp;)?nregaud=(\d+)",
                           row["infadicion"][0].replace("&amp;", "&")) \
                if row["infadicion"] else None
            rec["nreg"] = mm.group(1) if mm else None
            rec["nregaud"] = mm.group(2) if mm else rec["registro"]
            # substitution events?
            if rec["nreg"]:
                url = (BASE + "/portal/consultas/ifa/infadicionifa?id=0&lang=es"
                       f"&nreg={rec['nreg']}&nregaud={rec['nregaud']}")
                r = s.get(url, timeout=60)
                evs = [re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)
                       for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", r.text, re.S)]
                evs = [[re.sub(r"<[^>]+>|\s+", " ", c).strip() for c in e]
                       for e in evs]
                subst = [e for e in evs if e and
                         re.match(r"\d{2}/\d{2}/\d{4}", e[0])
                         and any("sustituci" in c.lower() or
                                 "replacement" in c.lower() for c in e)]
                rec["substitution_events_es"] = subst
            # dual signal: compare ZIP tokens across langs
            html_en, _ = resolve_results(s, denom, "en")
            row_en = next((r for r in all_rows(html_en)
                           if r["cells"][0] == rec["registro"]), None)
            rec["row_en"] = row_en
            zes = row["tokens"][-1] if row["tokens"] else None
            zen = (row_en["tokens"][-1] if row_en and row_en["tokens"]
                   else None)
            rec["zip_token_es"] = zes
            rec["zip_token_en"] = zen
            rec["zip_token_equal"] = (zes == zen) if zes and zen else None
            rec["status"] = "SUBSTITUTION" if rec.get(
                "substitution_events_es") else "NO_SUBSTITUTION"
        except Exception as e:  # noqa: BLE001
            rec["status"] = f"ERROR: {e}"
        out.append(rec)
        print(denom, "->", rec["status"],
              "| reg:", rec.get("registro"),
              "| subst:", len(rec.get("substitution_events_es") or []),
              "| zip_tok_equal:", rec.get("zip_token_equal"), flush=True)
    (HERE / "g1d_scan.json").write_bytes(
        json.dumps({"executed_at": datetime.now(timezone.utc).isoformat(),
                    "results": out}, indent=1, ensure_ascii=False)
        .encode("utf-8"))
    print("wrote g1d_scan.json")


if __name__ == "__main__":
    main()
