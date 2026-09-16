"""Taxonomy helpers — offline inspection of ESEF report packages.

Extension namespaces are detected from the targetNamespace of the .xsd
files inside the issuer package (taxonomy schemas are not embedded in
report packages), so this is fully offline.
"""
from __future__ import annotations

import io, re, zipfile

_XSD_TNS = re.compile(r'targetNamespace="([^"]+)"')


def package_lang_tag(pkg: bytes | zipfile.ZipFile) -> str | None:
    """'-es'/'-en' tag from the package root dir {LEI}-{date}-{lang}/."""
    z = pkg if isinstance(pkg, zipfile.ZipFile) else \
        zipfile.ZipFile(io.BytesIO(pkg))
    for rt in {n.split("/")[0] for n in z.namelist() if "/" in n}:
        m = re.search(r"-(es|en)$", rt)
        if m:
            return m.group(1)
    return None


def extension_namespaces(pkg: bytes | zipfile.ZipFile) -> set[str]:
    """Issuer extension namespaces = targetNamespace of in-package XSDs."""
    z = pkg if isinstance(pkg, zipfile.ZipFile) else \
        zipfile.ZipFile(io.BytesIO(pkg))
    out = set()
    for name in z.namelist():
        if name.endswith(".xsd"):
            head = z.read(name)[:8192].decode("utf-8", "replace")
            m = _XSD_TNS.search(head)
            if m:
                out.add(m.group(1))
    return out
