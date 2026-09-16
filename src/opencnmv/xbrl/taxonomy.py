"""Taxonomy helpers — offline inspection of ESEF report packages.

Extension namespaces are detected from the targetNamespace of the .xsd
files inside the issuer package (taxonomy schemas are not embedded in
report packages), so this is fully offline.
"""
from __future__ import annotations

import io, re, zipfile
from pathlib import Path

_XSD_TNS = re.compile(r'targetNamespace="([^"]+)"')


def _as_zip(pkg) -> zipfile.ZipFile:
    if isinstance(pkg, zipfile.ZipFile):
        return pkg
    if isinstance(pkg, (str, Path)):
        return zipfile.ZipFile(pkg)
    return zipfile.ZipFile(io.BytesIO(pkg))


def package_lang_tag(pkg: bytes | zipfile.ZipFile | str | Path) -> str | None:
    """'-es'/'-en' tag from the package root dir {LEI}-{date}-{lang}/."""
    z = _as_zip(pkg)
    for rt in {n.split("/")[0] for n in z.namelist() if "/" in n}:
        m = re.search(r"-(es|en)$", rt)
        if m:
            return m.group(1)
    return None


def extension_namespaces(pkg: bytes | zipfile.ZipFile | str | Path) -> set[str]:
    """Issuer extension namespaces = targetNamespace of in-package XSDs."""
    z = _as_zip(pkg)
    out = set()
    for name in z.namelist():
        if name.endswith(".xsd"):
            head = z.read(name)[:30000].decode("utf-8", "replace")
            m = _XSD_TNS.search(head)
            if m:
                out.add(m.group(1))
    return out


# --- frozen-corpus taxonomy resolution -------------------------------------
#
# The frozen corpus pins taxonomy packages by name + sha256 (R10). These
# helpers resolve only file NAMES inside a caller-supplied directory; the
# caller is responsible for verifying sha256 against the pinned manifest.

ESEF_TAXONOMY = {
    "FY2024": {
        "disclosure": "esef-2022",
        "package_names": ["esef_taxonomy_2022_v1.1.zip",
                          "ifrs-full_ifrs-2022-03-24-opencnmv-pkg.zip",
                          "xbrl-lei-2020-07-02-opencnmv-pkg.zip"],
    },
    "FY2025": {
        "disclosure": "esef-2024",
        "package_names": ["esef_taxonomy_2024.zip",
                          "ifrs-full_ifrs-2024-03-27-opencnmv-pkg.zip",
                          "xbrl-lei-2020-07-02-opencnmv-pkg.zip"],
    },
}
IPP_PACKAGE_NAME = "cnmv-ipp-2019-01-01-opencnmv-pkg.zip"


def esef_taxonomy_set(fy: str, tax_dir: Path) -> dict:
    spec = ESEF_TAXONOMY[fy]
    pkgs = [tax_dir / n for n in spec["package_names"]]
    missing = [p.name for p in pkgs if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"missing taxonomy packages: {missing}")
    return {"disclosure": spec["disclosure"],
            "packages": [str(p) for p in pkgs]}


def ipp_taxonomy_set(tax_dir: Path) -> dict:
    p = tax_dir / IPP_PACKAGE_NAME
    if not p.is_file():
        raise FileNotFoundError(f"missing taxonomy package: {p.name}")
    return {"disclosure": None, "packages": [str(p)]}
