# G1-D — extended scan: ALL result rows per issuer (publication window
# 2024-01-01..2026-12-31 covers FY2023/24/25 filings). For every row we
# record zip-token equality across lang views (dual signal) and fetch
# infadicionifa to detect substitution events. Intersection of
# DUAL + SUBSTITUTION is the falsification candidate.
from __future__ import annotations

import json, re
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"
import sys
sys.path.insert(0, str(HERE))
from g1d_scan import WATCHLIST, hidden_fields, post_search, all_rows, UA  # noqa

BASE = "https://www.cnmv.es"
SEARCH = BASE + "/Portal/consultas/busqueda?id=25&lang={lang}"
INFAD = BASE + "/portal/consultas/ifa/infadicionifa?id=0&lang=es&nreg={nreg}&nregaud={nregaud}"


def resolve_results(s, denom, lang, desde, hasta):
    url = SEARCH.format(lang=lang)
    r = s.get(url, timeout=60)
    hf = hidden_fields(r.text)
    data = {**hf,
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": denom,
            "ctl00$ContentPrincipal$wFechas$fecha_desde": desde,
            "ctl00$ContentPrincipal$wFechas$fecha_hasta": hasta}
    html = post_search(s, url, data, lang)
    if "lstSeleccion" in html and "btnSeleccionar" in html:
        opts = re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>',
                          html)
        pick = next(((v, t) for v, t in opts if "S.A." in t.upper()),
                    opts[-1] if opts else None)
        if pick:
            hf2 = hidden_fields(html)
            r2 = s.post(url, data={**hf2,
                        "ctl00$ContentPrincipal$wbusqueda$lstSeleccion": pick[0],
                        "ctl00$ContentPrincipal$wbusqueda$btnSeleccionar":
                            "Seleccionar" if lang == "es" else "Select"},
                        timeout=180, headers={"Referer": url})
            return r2.text
    return html


def events_es(s, nreg, nregaud):
    r = s.get(INFAD.format(nreg=nreg, nregaud=nregaud), timeout=60)
    evs = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
        if cells and re.match(r"\d{2}/\d{2}/\d{4}", cells[0]):
            evs.append(cells)
    return evs


def main():
    s = requests.Session()
    s.headers.update(UA)
    out = []
    for denom in WATCHLIST:
        try:
            rows_es = {r["cells"][0]: r for r in all_rows(
                resolve_results(s, denom, "es", "2024-01-01", "2026-12-31"))}
            rows_en = {r["cells"][0]: r for r in all_rows(
                resolve_results(s, denom, "en", "2024-01-01", "2026-12-31"))}
            for reg, row in sorted(rows_es.items()):
                re_ = rows_en.get(reg)
                zes = row["tokens"][-1] if row["tokens"] else None
                zen = re_["tokens"][-1] if re_ and re_["tokens"] else None
                dual = (zes is not None and zen is not None and zes != zen)
                rec = {"denom": denom, "registro": reg,
                       "period_end": row["cells"][1] if len(row["cells"]) > 1 else None,
                       "pub_date": row["cells"][2] if len(row["cells"]) > 2 else None,
                       "dual_zip_token": dual,
                       "en_row_present": re_ is not None}
                mm = re.search(r"nreg=(\d+)&nregaud=(\d+)",
                               row["infadicion"][0].replace("&amp;", "&")) \
                    if row["infadicion"] else None
                if mm:
                    evs = events_es(s, mm.group(1), mm.group(2))
                    rec["nreg"], rec["nregaud"] = mm.group(1), mm.group(2)
                    rec["events"] = evs
                    rec["substitutions"] = [e for e in evs if any(
                        "sustituci" in c.lower() for c in e)]
                if dual or rec.get("substitutions"):
                    print(denom, reg, "dual:", dual,
                          "subst:", len(rec.get("substitutions") or []),
                          flush=True)
                out.append(rec)
        except Exception as e:  # noqa: BLE001
            out.append({"denom": denom, "error": str(e)})
            print(denom, "ERR", e, flush=True)
    (HERE / "g1d_scan2.json").write_bytes(json.dumps(
        {"executed_at": datetime.now(timezone.utc).isoformat(),
         "results": out}, indent=1, ensure_ascii=False).encode("utf-8"))
    hits = [r for r in out if r.get("dual_zip_token")
            and r.get("substitutions")]
    print("\nDUAL+SUBSTITUTION hits:", len(hits))
    for h in hits:
        print(" ", h["denom"], h["registro"], h["period_end"])
    print("wrote g1d_scan2.json")


if __name__ == "__main__":
    main()
