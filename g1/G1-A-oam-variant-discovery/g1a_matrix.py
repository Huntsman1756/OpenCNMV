"""Regenerate g1a_results.json offline from preserved evidence.

Reads the six captured result pages (busqueda25-{issuer}-{es,en}.html) and the
preserved -en packages, recomputes the classification matrix with the
corrected model vocabulary:

  requested_ui_language      the UI language of the request (es|en)
  resolved_submission_language  the language tag of the artifact set served
  resolution_mode            SUBMITTED_VARIANT | FALLBACK_TO_ES
  submitted_variants         real per-filing variant list (fallback excluded)

Deterministic: identical evidence bytes -> identical matrix.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"

ISSUERS = [
    {"issuer": "SAN", "registros": {"20509": "FY2024", "20875": "FY2025"},
     "oracle_en_sha": {"20509": "47923b30c3763fe448ff8080bb3e38c50ae48d48171986a90947c8be347ccb37"}},
    {"issuer": "BBVA", "registros": {"20448": "FY2024", "20854": "FY2025"},
     "oracle_en_sha": {}},
    {"issuer": "IBE", "registros": {"20515": "FY2024", "20934": "FY2025"},
     "oracle_en_sha": {}},
]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def row_for(html: str, registro: str) -> dict | None:
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip() for t in tds]
        if cells and cells[0] == registro:
            return {"cells": cells,
                    "tokens": [t.replace("&amp;", "&")
                               for t in re.findall(r"verdocumento/ver\?e=([^\"']+)", row)],
                    "infadicion": re.findall(r"infadicionifa[^\"']+", row)}
    return None


def main() -> None:
    rows_raw = []
    pkg_sha = {}   # (issuer, registro, ui_lang) -> {sha, tag, bytes}
    for iss in ISSUERS:
        for lang in ("es", "en"):
            html = (EV / f"busqueda25-{iss['issuer']}-{lang}.html").read_text(
                encoding="utf-8")
            for registro, fy in iss["registros"].items():
                row = row_for(html, registro)
                rows_raw.append({"issuer": iss["issuer"], "registro": registro,
                                 "fy": fy, "ui_lang": lang, "row": row})
                pkg = EV / f"esef-{iss['issuer']}-{fy}-en.zip"
                if lang == "en" and pkg.exists():
                    body = pkg.read_bytes()
                    names = zipfile.ZipFile(io.BytesIO(body)).namelist()
                    rep = [n for n in names if "reports/" in n]
                    tag = "en" if rep and "-en/" in rep[0] else (
                          "es" if rep and "-es/" in rep[0] else "?")
                    pkg_sha[(iss["issuer"], registro, "en")] = {
                        "sha": sha256(body), "tag": tag, "bytes": len(body)}

    # -es packages are already preserved in the G0 corpus (R07 raw
    # artifacts); their sha256 values below were verified at capture time
    # against the CNMV-served bytes and recorded in the manifest.
    ES_KNOWN = {  # (issuer, registro) -> (sha256, tag)
        ("SAN", "20509"): ("725fff01861cb0c186107280bf30b2c047a3a59af703d799f678e02c435cb9f5", "es"),
        ("SAN", "20875"): ("07e95a16c7d1652d6c6298c39b19b6a1e90c5d4a8c01881b4ccaebdeaa700567", "es"),
        ("BBVA", "20448"): ("69f04da4f6ebe4f3072401207ff83f6edc9d335c83df666525594a7062d7248a", "es"),
        ("BBVA", "20854"): ("675a1d3a470fdc469beda39bf242ffcb496c6f1116da4d1fc562faa0734e3458", "es"),
        ("IBE", "20515"): ("89dfd3ef65527d1d4378464c2f70fa78b2fb7b4872264eacfa91d3faae1c42b4", "es"),
        ("IBE", "20934"): ("066fdaf835ad6e81f0ff77eacb571f5d2a09f9fb42788fbc12d7041d2e51e05a", "es"),
    }

    matrix = []
    for iss in ISSUERS:
        for registro, fy in iss["registros"].items():
            es = next(r for r in rows_raw if r["issuer"] == iss["issuer"]
                      and r["registro"] == registro and r["ui_lang"] == "es")
            en = next(r for r in rows_raw if r["issuer"] == iss["issuer"]
                      and r["registro"] == registro and r["ui_lang"] == "en")
            row_es, row_en = es["row"], en["row"]
            same_registry = (row_es and row_en
                             and row_es["cells"][0] == row_en["cells"][0] == registro
                             and row_es["infadicion"] == row_en["infadicion"])
            es_sha, es_tag = ES_KNOWN[(iss["issuer"], registro)]
            en_pkg = pkg_sha.get((iss["issuer"], registro, "en"))
            en_sha = en_pkg["sha"] if en_pkg else es_sha
            en_tag = en_pkg["tag"] if en_pkg else es_tag
            verdict = ("DISTINCT_REGISTRY_SUBMISSIONS" if not same_registry
                       else "SAME_REGISTRY_SAME_VERSION_VARIANTS")
            note = ("distinct -es/-en packages under one registro, "
                    "shared nreg+dates+history" if es_sha != en_sha
                    else "single submitted variant; lang=en is UI fallback")
            variants = sorted({es_tag, en_tag} & {"es", "en"})
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

    out = {"results": matrix, "rows_raw": rows_raw,
           "model_note": "requested_ui_language != resolved_submission_language; "
                         "lang=en resolving to the -es artifact set is FALLBACK_TO_ES, "
                         "not a second submitted variant"}
    (HERE / "g1a_results.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in matrix:
        print(r["issuer"], r["fy"], "->", r["verdict"],
              "| variants:", r["submitted_variants"],
              "| en mode:", r["resolution_mode"]["en"])


if __name__ == "__main__":
    main()
