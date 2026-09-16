"""G1-B DUAL_LANGUAGE_CAPTURE — capture stage.

For every in-scope ESEF registro (SAN/BBVA/IBE x FY2024/FY2025) POSTs the
official "Informes financieros anuales" search (busqueda.aspx?id=25) twice —
once per UI language (lang=es, lang=en) — resolves the served document set of
each UI view, downloads the canonical ESEF report package (DOC.ZIP role), and
probes the XHTM viewer documents by a streamed 256 KiB prefix (language marker
only; viewer bodies are resolution evidence, recorded as hashed prefixes).

Identity rule (per G1 design):

    variant_artifact_set_id = sha256 over canonical JSON of
        [["ESEF_PACKAGE_ZIP_XBRL", <package raw sha256>]]

    i.e. artifact sets deduplicate by officially served content, NEVER by
    requested_ui_language. The registry row exposes three document locators
    (ESEF_COVER, IXBRL_CONSOLIDATED, ESEF_PACKAGE_ZIP_XBRL); the canonical
    parseable artifact is the report package, which is what carries the XBRL
    semantics this gate compares. Viewer docs are recorded as locators plus a
    resolved-language marker from their prefix.

Per filing the inventory records, per view:
    requested_ui_language | resolved_submission_language |
    resolution_mode (SUBMITTED_VARIANT | FALLBACK_TO_ES) |
    variant_artifact_set_id | package sha256
and at filing level: submitted_variants / submitted_variant_count, obtained by
deduplicating views on variant_artifact_set_id.

Two runs (--run A / --run B) prove capture determinism under identical source
state: the compared product is the inventory core (resolved language, artifact
set id, resolution mode, package sha). Opaque verdocumento tokens and
timestamps are volatile and excluded from the core hash.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
G1A = REPO / "g1/G1-A-oam-variant-discovery"
G1A_EV = G1A / "evidence"
R07 = REPO / "g0-r/R07-raw-retrieval/evidence"
EV = HERE / "evidence"
RUNS = HERE / "_runs"

spec = importlib.util.spec_from_file_location("g1a_discover", G1A / "g1a_discover.py")
g1a = importlib.util.module_from_spec(spec)
sys.modules["g1a_discover"] = g1a
spec.loader.exec_module(g1a)

VERDOC = g1a.VERDOC
PREFIX_BYTES = 256 * 1024
UA = {"User-Agent": "OpenCNMV-G1B/1.0 (dual-language capture probe)"}

# token order inside a result row (verified in G1-A / R14)
ROLES = ["ESEF_COVER", "IXBRL_CONSOLIDATED", "ESEF_PACKAGE_ZIP_XBRL"]

ISSUERS = [
    {"issuer": "SAN", "denom": "BANCO SANTANDER",
     "registros": {"20509": "FY2024", "20875": "FY2025"}},
    {"issuer": "BBVA", "denom": "BILBAO VIZCAYA",
     "registros": {"20448": "FY2024", "20854": "FY2025"}},
    {"issuer": "IBE", "denom": "IBERDROLA",
     "registros": {"20515": "FY2024", "20934": "FY2025"}},
]

# preserved canonical package bytes (evidence from G0-R / G1-A)
def preserved_pkg(issuer: str, fy: str, lang: str) -> Path:
    if lang == "es":
        return R07 / f"esef-{issuer}-{fy}-package.zip"
    return G1A_EV / f"esef-{issuer}-{fy}-en.zip"


def sha256b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256f(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def variant_artifact_set_id(pkg_sha: str) -> str:
    """Content identity of the variant's canonical artifact set."""
    return sha256b(canon([["ESEF_PACKAGE_ZIP_XBRL", pkg_sha]]))


def pkg_lang_tag(body: bytes) -> str:
    """Resolved submission language from the report-package root dir, which is
    named {LEI}-{date}-[{n}-]{es|en}/ (e.g. 5493006QMFDDMYWIAM13-20241231-en/)."""
    if body[:2] != b"PK":
        return "?"
    z = zipfile.ZipFile(io.BytesIO(body))
    roots = {n.split("/", 1)[0] for n in z.namelist() if "/" in n}
    tags = {t for t in
            (r.rsplit("-", 1)[-1] for r in roots)
            if t in ("es", "en")}
    return sorted(tags)[0] if len(tags) == 1 else "?"


def prefix_probe(s: requests.Session, token: str) -> dict:
    """Stream at most PREFIX_BYTES of a viewer document; detect its declared
    language (xml:lang/lang attribute or <title>) without fetching the body."""
    r = s.get(VERDOC.format(tok=token), timeout=180, stream=True)
    try:
        buf = b""
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) >= PREFIX_BYTES:
                break
    finally:
        r.close()
    head = buf[:PREFIX_BYTES]
    m = re.search(rb'xml:lang="([a-zA-Z-]+)"', head) or \
        re.search(rb'<html[^>]*\slang="([a-zA-Z-]+)"', head) or \
        re.search(rb"/Lang\s*\(([a-zA-Z-]+)\)", head) or \
        re.search(rb"<dc:language>\s*<?xpacket[^>]*>?([^<]{2,10})", head) or \
        re.search(rb'http://purl.org/dc/[^>]*>\s*<rdf:li[^>]*>([a-zA-Z-]+)', head)
    t = re.search(rb"<title[^>]*>([^<]{0,200})", head) or \
        re.search(rb"<dc:title>.*?<rdf:li[^>]*>([^<]{0,200})", head, re.S)
    media = "PDF" if head[:5] == b"%PDF-" else (
            "XHTML" if b"<html" in head[:4096] else "?")
    return {"prefix_raw": head, "prefix_bytes": len(head),
            "prefix_sha256": sha256b(head), "media_hint": media,
            "content_type": r.headers.get("Content-Type"),
            "detected_lang": m.group(1).decode().lower() if m else None,
            "title": (t.group(1).decode("utf-8", "replace").strip()
                      if t else None)}


def fetch_pkg(s: requests.Session, token: str, dest: Path) -> dict:
    r = s.get(VERDOC.format(tok=token), timeout=600)
    r.raise_for_status()
    body = r.content
    dest.write_bytes(body)
    return {"sha256": sha256b(body), "bytes": len(body),
            "content_type": r.headers.get("Content-Type"),
            "lang_tag": pkg_lang_tag(body)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, choices=["A", "B"])
    a = ap.parse_args()
    cap_ev = EV / "capture" / f"run{a.run}"
    cap_ev.mkdir(parents=True, exist_ok=True)
    raw_dir = RUNS / f"capture-{a.run}" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update(UA)
    fetch_log = []
    filings = []

    for iss in ISSUERS:
        views = {}  # (registro, lang) -> view record
        for lang in ("es", "en"):
            html = g1a.search_ifa(s, iss["denom"], lang, "2024-01-01", "2026-09-30")
            pfn = f"busqueda25-{iss['issuer']}-{lang}.html"
            (cap_ev / pfn).write_text(html, encoding="utf-8")
            fetch_log.append({"kind": "SEARCH_PAGE", "file": pfn,
                              "sha256": sha256b(html.encode("utf-8")),
                              "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            for registro, fy in iss["registros"].items():
                row = g1a.row_for(html, registro)
                if not row:
                    views[(registro, lang)] = {"error": "ROW_NOT_FOUND",
                                               "requested_ui_language": lang}
                    continue
                toks = row["tokens"]
                pkg = fetch_pkg(s, toks[-1],
                                raw_dir / f"pkg-{iss['issuer']}-{fy}-{lang}.zip")
                # viewer language probes (prefix only)
                doc_lang = {}
                prefix_rec = []
                for role, tok in zip(ROLES, toks):
                    if role == "ESEF_PACKAGE_ZIP_XBRL":
                        doc_lang[role] = pkg["lang_tag"]
                        continue
                    pp = prefix_probe(s, tok)
                    pdir = cap_ev / "viewer-prefixes"
                    pdir.mkdir(exist_ok=True)
                    ppath = pdir / f"prefix-{iss['issuer']}-{fy}-{lang}-{role}.bin"
                    ppath.write_bytes(pp.pop("prefix_raw"))
                    doc_lang[role] = pp["detected_lang"]
                    prefix_rec.append({"role": role, **pp})
                time.sleep(0.3)
                resolved = pkg["lang_tag"]
                view = {
                    "requested_ui_language": lang,
                    "registry_row": {"registro": registro,
                                     "cells": row["cells"],
                                     "infadicion": row["infadicion"]},
                    "document_locators": dict(zip(ROLES, toks)),
                    "resolved_doc_language": doc_lang,
                    "viewer_prefix_probes": prefix_rec,
                    "package": {"sha256": pkg["sha256"], "bytes": pkg["bytes"],
                                "content_type": pkg["content_type"],
                                "lang_tag": pkg["lang_tag"]},
                    "resolved_submission_language": resolved,
                    "resolution_mode": ("SUBMITTED_VARIANT" if resolved == lang
                                        else f"FALLBACK_TO_{resolved.upper()}"),
                    "variant_artifact_set_id": variant_artifact_set_id(pkg["sha256"]),
                    "token_zip_identical_across_views": None,  # filled below
                }
                views[(registro, lang)] = view

        for registro, fy in iss["registros"].items():
            ves, ven = views[(registro, "es")], views[(registro, "en")]
            if "error" in ves or "error" in ven:
                filings.append({"issuer": iss["issuer"], "fy": fy,
                                "registro": registro, "error": "VIEW_MISSING"})
                continue
            # cross-view token invariance observation
            same_zip_tok = (ves["document_locators"]["ESEF_PACKAGE_ZIP_XBRL"]
                            == ven["document_locators"]["ESEF_PACKAGE_ZIP_XBRL"])
            for v in (ves, ven):
                v["token_zip_identical_across_views"] = same_zip_tok
            # preserved-bytes cross-check: each resolved package must match the
            # canonical preserved evidence for its resolved language
            for v in (ves, ven):
                rl = v["resolved_submission_language"]
                ref = preserved_pkg(iss["issuer"], fy, rl)
                v["preserved_reference"] = {
                    "path": str(ref.relative_to(REPO)),
                    "sha256": sha256f(ref),
                    "match": v["package"]["sha256"] == sha256f(ref),
                }
            # dedupe views by artifact-set identity (content, not UI language)
            sets = {}
            for lang, v in (("es", ves), ("en", ven)):
                sid = v["variant_artifact_set_id"]
                if sid not in sets:
                    sets[sid] = {"language": v["resolved_submission_language"],
                                 "artifact_set_id": sid,
                                 "package_sha256": v["package"]["sha256"],
                                 "served_to_views": []}
                sets[sid]["served_to_views"].append(lang)
            variants = sorted(sets.values(), key=lambda x: x["language"])
            filings.append({
                "issuer": iss["issuer"], "fy": fy, "registro": registro,
                "views": {"es": ves, "en": ven},
                "submitted_variants": variants,
                "submitted_variant_count": len(variants),
                # adversarial: wrong identity model = requested UI language
                "bad_model_variant_count": 2,   # len(requested ui langs)
            })

    filings.sort(key=lambda f: (f["issuer"], f["fy"]))
    inv = {"gate": "G1-B", "stage": "capture", "run": a.run,
           "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "filings": filings, "fetch_log": fetch_log}
    (cap_ev / "variant_inventory.json").write_text(
        json.dumps(inv, indent=1, ensure_ascii=False), encoding="utf-8")

    def core(fl):
        return {"registro": fl["registro"],
                "views": {l: {"resolved": v["resolved_submission_language"],
                              "mode": v["resolution_mode"],
                              "set": v["variant_artifact_set_id"],
                              "pkg": v["package"]["sha256"],
                              "doc_lang": v["resolved_doc_language"],
                              "preserved_match": v["preserved_reference"]["match"]}
                          for l, v in fl["views"].items()},
                "submitted_variants": fl["submitted_variants"],
                "submitted_variant_count": fl["submitted_variant_count"]}
    core_map = {f["registro"]: core(f) for f in filings if "views" in f}
    (cap_ev / "inventory_core_sha256.txt").write_text(
        sha256b(canon(core_map)) + "\n", encoding="utf-8")
    print(f"run {a.run}: filings={len(filings)} "
          f"inventory_core_sha256={sha256b(canon(core_map))[:16]}…")
    for f in filings:
        if "views" in f:
            print(f"  {f['issuer']} {f['fy']}: variants={f['submitted_variant_count']} "
                  f"en_mode={f['views']['en']['resolution_mode']} "
                  f"es_sha={f['views']['es']['package']['sha256'][:12]}… "
                  f"en_sha={f['views']['en']['package']['sha256'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())
