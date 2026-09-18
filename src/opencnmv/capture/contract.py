"""Frozen-corpus capture contract: scope, identity registry, courtesy.

The issuer registry below is *scope*, not data: it pins exactly which
issuers the capture path may touch and the identities used for CNMV
surfaces. Expansion beyond the frozen corpus is G3 work.
"""
from __future__ import annotations

CAPTURE_MANIFEST_FORMAT = "CNMV_CAPTURE_V1"

USER_AGENT = ("OpenCNMV/0.1.0 controlled-capture "
              "(canonical archive; contact via repository)")
MIN_DELAY_S = 1.0

# Frozen issuer corpus (AGENTS.md §4). Keys are the CNMV NIF used by the
# listaifi surface; denomination is the busqueda?id=25 search term.
ISSUERS: dict[str, dict] = {
    "A39000013": {"key": "SAN", "denomination": "BANCO SANTANDER, S.A.",
                  "lei": "5493006QMFDDMYWIAM13"},
    "A48265169": {"key": "BBVA",
                  "denomination": "BANCO BILBAO VIZCAYA ARGENTARIA, S.A.",
                  "lei": "K8MS7FD7N5Z2WQ51AZ71"},
    "A-48010615": {"key": "IBE", "denomination": "IBERDROLA, S.A.",
                   "lei": "5QK37QC7NWOJ8D7WVQ45"},
}

# IPP slots: (semester token as served by listaifi, year).
IPP_SLOTS = (("I", 2024), ("II", 2024), ("I", 2025), ("II", 2025),
             ("I", 2026))

# ESEF periods in scope, as served by the registry cells (dd/mm/yyyy).
ESEF_PERIODS = ("31/12/2024", "31/12/2025")
ESEF_FY = {"31/12/2024": "FY2024", "31/12/2025": "FY2025"}

# busqueda?id=25 filing-date window covering the frozen corpus.
SEARCH_FROM = "2024-01-01"
SEARCH_TO = "2026-12-31"

# verdocumento token roles on the IFA registry row, in document order.
ESEF_TOKEN_ROLES = ("ESEF_COVER", "IXBRL_CONSOLIDATED",
                    "ESEF_PACKAGE_ZIP_XBRL")

# External issuer registry input (G3-A): {nif -> {key, denomination,
# lei, scope?}}. Issuer sets are *input data*, never hardcoded branches;
# an entry may pin ``scope = {"esef_periods": [...], "ipp_slots":
# [[semester, year], ...]}`` — absent scope falls back to the frozen
# module defaults above.
ISSUER_REGISTRY_FORMAT = "ISSUER_REGISTRY_V1"


def load_issuer_registry(path) -> dict[str, dict]:
    """Load an ISSUER_REGISTRY_V1 file. Fail closed on malformed input."""
    import json
    from pathlib import Path

    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise CaptureError(f"issuer registry unreadable: {p} ({ex})")
    if not isinstance(doc, dict) or \
            doc.get("format") != ISSUER_REGISTRY_FORMAT:
        raise CaptureError(
            f"{p}: format != {ISSUER_REGISTRY_FORMAT}")
    issuers = doc.get("issuers")
    if not isinstance(issuers, dict) or not issuers:
        raise CaptureError(f"{p}: no issuers")
    out: dict[str, dict] = {}
    for nif, e in issuers.items():
        if not isinstance(e, dict) or not e.get("key") \
                or not e.get("denomination"):
            raise CaptureError(
                f"{p}: issuer {nif} lacks key/denomination")
        scope = e.get("scope")
        if scope is not None:
            if not isinstance(scope, dict) or not all(
                    isinstance(scope.get(k), list)
                    for k in ("esef_periods", "ipp_slots")):
                raise CaptureError(
                    f"{p}: issuer {nif} malformed scope")
            scope = {"esef_periods": list(scope["esef_periods"]),
                     "ipp_slots": [(s, y) for s, y in
                                   scope["ipp_slots"]]}
        out[nif] = {**e, "scope": scope}
    return out


class CaptureError(RuntimeError):
    """Source/network/discovery failure -> CLI exit code 7."""


class TaxonomyUnresolvedError(CaptureError):
    """A filing declares/requires a taxonomy with no pinned package set.

    Raised (rather than a bare KeyError) so assembly can classify the
    outcome as TAXONOMY_UNRESOLVED instead of aborting the capture."""
