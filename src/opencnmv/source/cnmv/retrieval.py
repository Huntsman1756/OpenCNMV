"""CNMV artifact retrieval — verdocumento. Callers preserve raw bytes;
helpers classify kind and extract the package language tag."""
from __future__ import annotations

import io
import math
import re
import time
import zipfile

import requests

BASE = "https://www.cnmv.es"
VERDOC = BASE + "/webservices/verdocumento/ver?e={tok}"


def fetch_document(s: requests.Session, token: str, *,
                   max_bytes: int = 128 * 1024 * 1024,
                   max_seconds: float = 600) -> tuple[bytes, str]:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive")
    deadline = time.monotonic() + max_seconds
    with s.get(VERDOC.format(tok=token), stream=True,
               timeout=(min(10, max_seconds), min(60, max_seconds))) as r:
        r.raise_for_status()
        length = r.headers.get("Content-Length", "")
        if length.isascii() and length.isdecimal() and int(length) > max_bytes:
            raise ValueError("Document exceeds max_bytes")
        body = bytearray()
        if time.monotonic() >= deadline:
            raise requests.Timeout("Document retrieval exceeded max_seconds")
        for chunk in r.iter_content(chunk_size=65536):
            if time.monotonic() >= deadline:
                raise requests.Timeout("Document retrieval exceeded max_seconds")
            if len(body) + len(chunk) > max_bytes:
                raise ValueError("Document exceeds max_bytes")
            body.extend(chunk)
        if time.monotonic() >= deadline:
            raise requests.Timeout("Document retrieval exceeded max_seconds")
        return bytes(body), r.headers.get("Content-Type", "")


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
