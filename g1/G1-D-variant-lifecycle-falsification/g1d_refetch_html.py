# G1-D — re-fetch the HTML evidence pages preserving RAW SERVED BYTES.
# The original captures used write_text() (CRLF on Windows), which does not
# reproduce the recorded sha256. This script re-downloads the same official
# pages, saves r.content verbatim and updates the manifest entries.
from __future__ import annotations

import hashlib, json, re
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"

BASE = "https://www.cnmv.es"
SEARCH = BASE + "/Portal/consultas/busqueda?id=25&lang={lang}"
INFAD = BASE + "/portal/consultas/ifa/infadicionifa?id=0&lang={lang}&nreg={nreg}&nregaud={nregaud}"
UA = {"User-Agent": "OpenCNMV-G1D/1.0 (evidence probe)"}

ISSUERS = {  # denom used in the POST, date range, (nreg, nregaud)
    "AMPER":      {"denom": "AMPER",      "desde": "2025-01-01",
                   "nreg": "2026031562", "nregaud": "20938"},
    "BANKINTER":  {"denom": "BANKINTER",  "desde": "2025-01-01",
                   "nreg": "2026026888", "nregaud": "20860"},
    "URBAR":      {"denom": "URBAR",      "desde": "2025-01-01",
                   "nreg": "2026073666", "nregaud": "21257"},
    "TELEFONICA": {"denom": "TELEFONICA", "desde": "2024-01-01",
                   "nreg": "2025030764", "nregaud": "20484"},
}


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


def search_bytes(s, denom, lang, desde):
    url = SEARCH.format(lang=lang)
    r = s.get(url, timeout=60)
    data = {**hidden_fields(r.text),
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": denom,
            "ctl00$ContentPrincipal$wFechas$fecha_desde": desde,
            "ctl00$ContentPrincipal$wFechas$fecha_hasta": "2026-12-31",
            "ctl00$ContentPrincipal$wFechas$ult_dias": "",
            "ctl00$ContentPrincipal$btnOk":
                "Search" if lang == "en" else "Buscar"}
    r2 = s.post(url, data=data, timeout=180, headers={"Referer": url})
    r2.raise_for_status()
    if "lstSeleccion" in r2.text and "btnSeleccionar" in r2.text:
        opts = re.findall(
            r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', r2.text)
        pick = next((o for o in opts if "S.A." in o[1].upper()),
                    opts[-1] if opts else None)
        if pick:
            data2 = {**hidden_fields(r2.text),
                     "ctl00$ContentPrincipal$wbusqueda$lstSeleccion": pick[0],
                     "ctl00$ContentPrincipal$wbusqueda$btnSeleccionar":
                         "Seleccionar" if lang == "es" else "Select"}
            r3 = s.post(url, data=data2, timeout=180,
                        headers={"Referer": url})
            r3.raise_for_status()
            return r3.content
    return r2.content


def main():
    s = requests.Session()
    s.headers.update(UA)
    mp = HERE / "manifest.json"
    man = json.loads(mp.read_text(encoding="utf-8"))
    by_file = {a["file"]: a for a in man["artifacts"]}
    updated = []
    for iss, p in ISSUERS.items():
        for lang in ("es", "en"):
            body = search_bytes(s, p["denom"], lang, p["desde"])
            fn = f"busqueda25-{iss}-{lang}.html"
            (EV / fn).write_bytes(body)
            by_file[f"evidence/{fn}"].update(
                sha256=sha256(body), bytes=len(body),
                note="raw served bytes (refetched after CRLF fix)")
            updated.append(fn)
            url = INFAD.format(lang=lang, nreg=p["nreg"],
                               nregaud=p["nregaud"])
            r = s.get(url, timeout=60)
            r.raise_for_status()
            fn = f"infadicionifa-{iss}-{lang}.html"
            (EV / fn).write_bytes(r.content)
            by_file[f"evidence/{fn}"].update(
                sha256=sha256(r.content), bytes=len(r.content),
                note="raw served bytes (refetched after CRLF fix)")
            updated.append(fn)
        print(iss, "done", flush=True)
    mp.write_bytes(json.dumps(man, indent=1, ensure_ascii=False)
                   .encode("utf-8"))
    print("updated", len(updated), "files + manifest")


if __name__ == "__main__":
    main()
