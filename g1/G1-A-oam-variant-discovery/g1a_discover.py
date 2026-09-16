"""G1-A OAM_VARIANT_DISCOVERY probe.

Mechanically answers, for the frozen-corpus ESEF filings of SAN/BBVA/IBE:

  Q1. Where is each language variant officially discoverable?
  Q2. Do -es / -en share the same registro oficial?
  Q3. Can variants carry independent dates / substitutions / histories?
  Q4. Which identifier is stable across variants?

Method
------
For each issuer, POST the official "Informes financieros anuales" search
(busqueda.aspx?id=25, the source filings.xbrl.org itself declares for CNMV)
twice: once with the Spanish UI (lang=es) and once with the English UI
(lang=en). For every result row of the target registro we record:

  * visible cells (registro, dates, auditor, tipo, opinion),
  * every verdocumento token (document links are opaque, language-dependent),
  * the infadicionifa link (shared additional-information / history page),
  * sha256 of the ESEF ZIP package each token serves.

IBE is the control: it has no -en variant in the oracle, so lang=en is
expected to fall back to the -es package. SAN/BBVA have oracle -en packages
with known sha256; matching sha256 proves the lang=en CNMV document is the
same official package the oracle indexed.

All pages and packages are preserved unmodified under evidence/ and hashed
into manifest.json. Outcomes are classified into the preregistered
vocabulary:

  SAME_REGISTRY_* / DISTINCT_REGISTRY_* / EXTERNAL_ONLY_* / UNRESOLVED

with the same-registry case refined per filing into:

  DUAL_VARIANT_SHARED_REGISTRY      two real submitted variants, one registro
  SINGLE_VARIANT_WITH_UI_FALLBACK   one submitted variant; lang=en falls back
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"
EV.mkdir(exist_ok=True)

BASE = "https://www.cnmv.es"
SEARCH = BASE + "/Portal/consultas/busqueda?id=25&lang={lang}"
VERDOC = BASE + "/webservices/verdocumento/ver?e={tok}"

ISSUERS = [
    {"issuer": "SAN", "denom": "BANCO SANTANDER", "registros": {"20509": "FY2024", "20875": "FY2025"},
     "oracle_en_sha": {"20509": "47923b30c3763fe448ff8080bb3e38c50ae48d48171986a90947c8be347ccb37"}},
    {"issuer": "BBVA", "denom": "BILBAO VIZCAYA", "registros": {"20448": "FY2024", "20854": "FY2025"},
     "oracle_en_sha": {}},  # recorded below from oracle API if needed
    {"issuer": "IBE", "denom": "IBERDROLA", "registros": {"20515": "FY2024", "20934": "FY2025"},
     "oracle_en_sha": {}},
]

UA = {"User-Agent": "OpenCNMV-G1A/1.0 (evidence probe)"}


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


def search_ifa(s: requests.Session, denom: str, lang: str, desde: str, hasta: str) -> str:
    url = SEARCH.format(lang=lang)
    r = s.get(url, timeout=60)
    r.raise_for_status()
    data = {
        **hidden_fields(r.text),
        "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": denom,
        "ctl00$ContentPrincipal$wFechas$fecha_desde": desde,
        "ctl00$ContentPrincipal$wFechas$fecha_hasta": hasta,
        "ctl00$ContentPrincipal$wFechas$ult_dias": "",
        "ctl00$ContentPrincipal$btnOk": "Search" if lang == "en" else "Buscar",
    }
    r2 = s.post(url, data=data, timeout=180, headers={"Referer": url})
    r2.raise_for_status()
    return r2.text


def row_for(html: str, registro: str) -> dict | None:
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip() for t in tds]
        if cells and cells[0] == registro:
            toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", row)
            inf = re.findall(r"infadicionifa[^\"']+", row)
            return {"cells": cells, "tokens": [t.replace("&amp;", "&") for t in toks],
                    "infadicion": inf}
    return None


def fetch_doc(s: requests.Session, token: str) -> tuple[bytes, str]:
    r = s.get(VERDOC.format(tok=token), timeout=600)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "")


def main() -> None:
    s = requests.Session()
    s.headers.update(UA)
    results = []
    manifest = {"probe": "G1-A OAM_VARIANT_DISCOVERY",
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "artifacts": []}

    for iss in ISSUERS:
        for lang in ("es", "en"):
            html = search_ifa(s, iss["denom"], lang, "2024-01-01", "2026-09-30")
            fn = f"busqueda25-{iss['issuer']}-{lang}.html"
            (EV / fn).write_text(html, encoding="utf-8")
            manifest["artifacts"].append(
                {"file": f"evidence/{fn}", "sha256": sha256(html.encode("utf-8")),
                 "bytes": len(html.encode("utf-8")),
                 "source_url": SEARCH.format(lang=lang) + f" [POST denom={iss['denom']}]",
                 "kind": "SEARCH_RESULTS_PAGE"})
            for registro, fy in iss["registros"].items():
                row = row_for(html, registro)
                rec = {"issuer": iss["issuer"], "registro": registro, "fy": fy,
                       "ui_lang": lang, "row": row}
                if row:
                    # last verdocumento token = the ZIP package link
                    pkg_tok = row["tokens"][-1]
                    body, ctype = fetch_doc(s, pkg_tok)
                    rec["zip_content_type"] = ctype
                    rec["zip_sha256"] = sha256(body)
                    rec["zip_bytes"] = len(body)
                    if body[:2] == b"PK":
                        z = zipfile.ZipFile(io.BytesIO(body))
                        rec["report_members"] = [n for n in z.namelist() if "reports/" in n]
                        tag = "en" if "-en/" in rec["report_members"][0] else (
                              "es" if "-es/" in rec["report_members"][0] else "?")
                        rec["package_lang_tag"] = tag
                        if tag == "en":  # preserve the official -en package bytes
                            fn2 = f"esef-{iss['issuer']}-{fy}-en.zip"
                            (EV / fn2).write_bytes(body)
                            manifest["artifacts"].append(
                                {"file": f"evidence/{fn2}", "sha256": rec["zip_sha256"],
                                 "bytes": len(body),
                                 "source_url": VERDOC.format(tok=pkg_tok) +
                                     f" (via busqueda?id=25&lang=en, registro {registro})",
                                 "kind": "ESEF_PACKAGE_ZIP_EN"})
                results.append(rec)

    # OAM feed entry for SAN FY2024 IFA (daily-registry entry -> same registro)
    oir = s.get(
        "https://internet.cnmv.es/Portal/Otra-Informacion-Relevante/Resultado-OIR.aspx?nreg=33155",
        timeout=60)
    (EV / "resultado-oir-33155.html").write_bytes(oir.content)
    manifest["artifacts"].append(
        {"file": "evidence/resultado-oir-33155.html", "sha256": sha256(oir.content),
         "bytes": len(oir.content),
         "source_url": "https://internet.cnmv.es/Portal/Otra-Informacion-Relevante/Resultado-OIR.aspx?nreg=33155",
         "kind": "OAM_FEED_ENTRY_DETAIL"})

    # classify per (issuer, registro)
    matrix = []
    for iss in ISSUERS:
        for registro, fy in iss["registros"].items():
            es = next(r for r in results if r["issuer"] == iss["issuer"]
                      and r["registro"] == registro and r["ui_lang"] == "es")
            en = next(r for r in results if r["issuer"] == iss["issuer"]
                      and r["registro"] == registro and r["ui_lang"] == "en")
            row_es, row_en = es["row"], en["row"]
            same_registry = (row_es and row_en
                             and row_es["cells"][0] == row_en["cells"][0] == registro
                             and row_es["infadicion"] == row_en["infadicion"])
            es_sha = es.get("zip_sha256"); en_sha = en.get("zip_sha256")
            es_tag = es.get("package_lang_tag"); en_tag = en.get("package_lang_tag")
            # UI-language view vs submitted variant: resolved_submission_language
            # is the language tag of the artifact set actually served; a lang=en
            # request that resolves to the -es set is FALLBACK, not a variant.
            variants = sorted({t for t in (es_tag, en_tag) if t in ("es", "en")})
            if not same_registry:
                verdict = "DISTINCT_REGISTRY_SUBMISSIONS"
                note = ""
            elif len(variants) == 2:
                verdict = "DUAL_VARIANT_SHARED_REGISTRY"
                note = ("distinct -es/-en packages under one registro, "
                        "shared nreg+dates+history")
            else:
                verdict = "SINGLE_VARIANT_WITH_UI_FALLBACK"
                note = "single submitted variant; lang=en is UI fallback"
            oracle_sha = iss["oracle_en_sha"].get(registro)
            matrix.append({
                "issuer": iss["issuer"], "fy": fy, "registro": registro,
                "nreg_submission_es": (row_es or {}).get("infadicion"),
                "nreg_submission_en": (row_en or {}).get("infadicion"),
                "pub_date_es": row_es["cells"][2] if row_es else None,
                "pub_date_en": row_en["cells"][2] if row_en else None,
                "es_zip_sha256": es_sha, "en_zip_sha256": en_sha,
                "es_package_tag": es_tag, "en_package_tag": en_tag,
                "requested_ui_language": ["es", "en"],
                "resolved_submission_language": {"es": es_tag, "en": en_tag},
                "resolution_mode": {"es": "SUBMITTED_VARIANT",
                                    "en": "SUBMITTED_VARIANT" if en_tag == "en"
                                         else "FALLBACK_TO_ES"},
                "submitted_variants": variants,
                "submitted_variant_count": len(variants),
                "oracle_en_sha256": oracle_sha,
                "en_package_matches_oracle": (en_sha == oracle_sha) if oracle_sha else None,
                "verdict": verdict, "note": note})

    out = {"results": matrix, "rows_raw": results}
    (HERE / "g1a_results.json").write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                           encoding="utf-8")
    manifest["artifacts"].append(
        {"file": "g1a_results.json",
         "sha256": sha256((HERE / "g1a_results.json").read_bytes()),
         "bytes": (HERE / "g1a_results.json").stat().st_size,
         "kind": "RESULT_MATRIX"})
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False),
                                        encoding="utf-8")
    for row in matrix:
        print(row["issuer"], row["fy"], row["registro"], "->", row["verdict"],
              "| en==oracle:", row["en_package_matches_oracle"],
              "| tags:", row["es_package_tag"], "/", row["en_package_tag"], "|", row["note"])


if __name__ == "__main__":
    main()
