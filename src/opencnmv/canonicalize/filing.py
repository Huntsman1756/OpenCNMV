"""Canonical filing assembly — V1 layout, deterministic field order."""
from __future__ import annotations

from opencnmv.model import ids


def new_filing(registro: str, issuer: dict, period_end: str,
               family: str = "ESEF_IFA") -> dict:
    return {
        "filing_id": ids.filing_id(registro),
        "issuer": issuer,
        "registro_oficial": registro,
        "family": family,
        "period_end": period_end,
        "filing_versions": [],
        "submission_variants": [],
        "view_resolutions": [],
        "version_events": [],
        "extension_mappings": []}


def filing_version(filing_id: str, nreg: str | None,
                   filed_at: str | None = None,
                   submission_kind: str | None = None) -> dict:
    return {
        "filing_version_id": ids.filing_version_id(filing_id, nreg or "?"),
        "source_nreg": nreg,
        "filed_at": filed_at,
        "submission_kind": submission_kind}


def artifact(role: str, sha256: str, bytes_: int | None = None,
             media_type: str | None = None, source_url: str | None = None,
             package_lang_tag: str | None = None) -> dict:
    a: dict = {"artifact_id": ids.artifact_id(sha256), "role": role,
               "sha256": sha256}
    if bytes_ is not None:
        a["bytes"] = bytes_
    if media_type is not None:
        a["media_type"] = media_type
    if source_url is not None:
        a["source_url"] = source_url
    a["package_lang_tag"] = package_lang_tag  # explicit null allowed
    return a
