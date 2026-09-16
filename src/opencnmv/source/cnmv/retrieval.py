"""CNMV artifact retrieval — verdocumento. Callers preserve raw bytes;
helpers classify kind and extract the package language tag."""
from __future__ import annotations

import io, re, zipfile

import requests

BASE = "https://www.cnmv.es"
VERDOC = BASE + "/webservices/verdocumento/ver?e={tok}"


def fetch_document(s: requests.Session, token: str) -> tuple[bytes, str]:
    r = s.get(VERDOC.format(tok=token), timeout=600)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "")


def doc_kind(body: bytes) -> str:
    if body[:2] == b"PK":
        return "ESEF_PACKAGE_ZIP"
    if body[:4] == b"%PDF":
        return "DOC_PDF"
    if b"html" in body[:500].lower():
        return "DOC_XHTML"
    return "DOC_OTHER"


def package_lang_tag(body_or_zip) -> str | None:
    """'-es'/'-en' tag from the ESEF package root dir {LEI}-{date}-{lang}/."""
    z = (body_or_zip if isinstance(body_or_zip, zipfile.ZipFile)
         else zipfile.ZipFile(io.BytesIO(body_or_zip)))
    for rt in {n.split("/")[0] for n in z.namelist() if "/" in n}:
        m = re.search(r"-(es|en)$", rt)
        if m:
            return m.group(1)
    return None
