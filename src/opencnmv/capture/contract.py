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


class CaptureError(RuntimeError):
    """Source/network/discovery failure -> CLI exit code 7."""
