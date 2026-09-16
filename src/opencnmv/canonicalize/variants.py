"""submission_variant / variant_version / view_resolution assembly.

Invariants enforced here:
  I1  a UI view resolving to another language's artifact set is a
      view_resolution (FALLBACK), never a variant.
  I2  variant_id = filing#language — stable, never a content hash.
  I3  variant_version carries artifact_set_id (content identity).
"""
from __future__ import annotations

from opencnmv.model import ids


def variant(filing_id: str, lang: str) -> dict:
    vid = ids.variant_id(filing_id, lang)
    return {"variant_id": vid, "filing_id": filing_id,
            "submission_language": lang, "variant_versions": []}


def variant_version(variant_id: str, n: int, observed: bool,
                    artifact_set_id: str | None = None,
                    artifacts: list | None = None,
                    created_by_event_id: str | None = None,
                    supersedes: str | None = None) -> dict:
    return {"variant_version_id": ids.variant_version_id(variant_id, n),
            "variant_id": variant_id,
            "observed": observed,
            "artifact_set_id": artifact_set_id,
            "artifacts": artifacts or [],
            "created_by_event_id": created_by_event_id,
            "supersedes_variant_version_id": supersedes}


def view_resolution(filing_id: str, requested_lang: str,
                    resolved_lang: str, resolution_mode: str) -> dict:
    return {"requested_ui_language": requested_lang,
            "resolved_variant_id": ids.variant_id(filing_id, resolved_lang),
            "resolution_mode": resolution_mode}
