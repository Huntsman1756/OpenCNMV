"""version_event assembly + lifecycle scope classification (G1-D rules).

Scope rule (preregistered):
  EN_ONLY_REPLACED / ES_ONLY_REPLACED  <- reason clause explicitly scopes
      the replaced artefact to one language version.
  BOTH_VARIANTS_REPLACED             <- only with explicit evidence for
      both artefact sets — never inferred from shared registry/date.
  VARIANT_SCOPE_NOT_OBSERVABLE       <- otherwise.
  NOT_A_VERSION_TRANSITION           <- certificate rows that create no
      version transition (R13 semantics).
"""
from __future__ import annotations

import re

from opencnmv.model import ids

SCOPE_VOCABULARY = ("BOTH_VARIANTS_REPLACED", "ES_ONLY_REPLACED",
                    "EN_ONLY_REPLACED", "VARIANT_SCOPE_NOT_OBSERVABLE")


def reason_clause(text: str, anchor: str | None = None) -> str | None:
    """Extract the 'motivo de la sustitución es/fue ...' clause to end of
    paragraph, so periods inside 'S.A.' / '20484.' do not truncate it."""
    if anchor:
        m = re.search(anchor + r".*?motivo de la sustituci[oó]n es\s+"
                      r"(.+?)(?:\n\s*\n|Y,\s*para)", text, re.S | re.I)
    else:
        m = re.search(r"motivo de la sustituci[oó]n\s+(?:es|fue)\s+"
                      r"(.+?)(?:\n\s*\n|Y,\s*para)", text, re.S | re.I)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".")


def classify_scope(reason: str | None) -> tuple[str, str]:
    if not reason:
        return ("VARIANT_SCOPE_NOT_OBSERVABLE", "no reason clause extracted")
    en = re.search(r"versi[oó]n en ingl[eé]s", reason, re.I)
    es = re.search(r"versi[oó]n en (espa[nñ]ol|castellano)", reason, re.I)
    if en and not es:
        return ("EN_ONLY_REPLACED",
                "reason clause explicitly scopes the replaced artefact to "
                "the English published version")
    if es and not en:
        return ("ES_ONLY_REPLACED",
                "reason clause explicitly scopes the replaced artefact to "
                "the Spanish published version")
    if en and es:
        return ("BOTH_VARIANTS_REPLACED",
                "reason clause references both language versions")
    return ("VARIANT_SCOPE_NOT_OBSERVABLE",
            "reason clause does not identify the affected artefact set at "
            "variant granularity")


def event(filing_id: str, key: str, event_type: str,
          event_date: str | None = None, source_label: str | None = None,
          source_nreg: str | None = None,
          evidence_artifact_id: str | None = None,
          scope_status: str = "NOT_A_VERSION_TRANSITION",
          affects: list | None = None) -> dict:
    return {"event_id": ids.event_id(filing_id, key),
            "event_date": event_date, "event_type": event_type,
            "source_label": source_label, "source_nreg": source_nreg,
            "evidence_artifact_id": evidence_artifact_id,
            "scope_status": scope_status, "affects": affects or []}


def affects(variant_id: str | None = None,
            component_scope: str = "NOT_IDENTIFIED",
            component_description: str | None = None,
            before: str | None = None, after: str | None = None,
            scope_basis: str | None = None) -> dict:
    return {"variant_id": variant_id,
            "affected_component_scope": component_scope,
            "component_description": component_description,
            "before_variant_version_id": before,
            "after_variant_version_id": after,
            "scope_basis": scope_basis}
