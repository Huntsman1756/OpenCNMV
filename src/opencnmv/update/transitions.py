"""Transition vocabulary for incremental dataset updates (G2-D contract).

A transition is a semantic fact about (S0, O1): what changed between the
recorded canonical state and a new authoritative observation. Transitions
are recorded in the delta; they never silently coerce unresolved source
changes into a known class.

Closed vocabulary — extend only by explicit amendment:

  NO_CHANGE                    observation == recorded state
  NEW_FILING                   filing_id unknown in S0
  NEW_FILING_VERSION           new source submission record (nreg)
  NEW_SUBMISSION_VARIANT       new stable variant identity (never from UI
                               language alone — only real submitted bytes)
  NEW_VARIANT_VERSION          new content state of an existing/new variant
  NEW_VERSION_EVENT            new lifecycle event
  VARIANT_SCOPED_VERSION_EVENT   event whose affects scope to a variant
                               subset
  FILING_SCOPE_NOT_OBSERVABLE    event recorded but affected scope is not
                               observable from the evidence — no variant
                               transition may be fabricated
  ARTIFACT_CHANGED             artifact content differs inside a NEW
                               version (vs the superseded version's set)
  ARTIFACT_ADDED               artifact appears inside a NEW version
  ARTIFACT_REMOVED             artifact absent from a NEW version's set
                               relative to its predecessor (classification
                               only — historical artifact rows are never
                               physically deleted)
  FACT_ADDED / FACT_REMOVED / FACT_PAYLOAD_CHANGED
                               structural-key comparison between a new
                               variant_version's facts and the superseded
                               version's facts
  EXTENSION_MAPPING_ADDED / EXTENSION_MAPPING_CHANGED
                               mapping evidence evolved (CHANGED allowed
                               only on the analysis metadata surface; only
                               PROVEN_EQUIVALENT may set rewrites_identity)
  VIEW_RESOLUTION_RECORDED     a new UI-language resolution row (never
                               creates a variant)
  SOURCE_STATE_CONFLICT        observation contradicts recorded history
                               (e.g. different content under an existing
                               identity) — never auto-resolved
  UNRESOLVED                   evidence insufficient to classify safely —
                               zero row ops for the affected filing
"""
from __future__ import annotations

NO_CHANGE = "NO_CHANGE"
NEW_FILING = "NEW_FILING"
NEW_FILING_VERSION = "NEW_FILING_VERSION"
NEW_SUBMISSION_VARIANT = "NEW_SUBMISSION_VARIANT"
NEW_VARIANT_VERSION = "NEW_VARIANT_VERSION"
NEW_VERSION_EVENT = "NEW_VERSION_EVENT"
VARIANT_SCOPED_VERSION_EVENT = "VARIANT_SCOPED_VERSION_EVENT"
FILING_SCOPE_NOT_OBSERVABLE = "FILING_SCOPE_NOT_OBSERVABLE"
ARTIFACT_CHANGED = "ARTIFACT_CHANGED"
ARTIFACT_ADDED = "ARTIFACT_ADDED"
ARTIFACT_REMOVED = "ARTIFACT_REMOVED"
FACT_ADDED = "FACT_ADDED"
FACT_REMOVED = "FACT_REMOVED"
FACT_PAYLOAD_CHANGED = "FACT_PAYLOAD_CHANGED"
EXTENSION_MAPPING_ADDED = "EXTENSION_MAPPING_ADDED"
EXTENSION_MAPPING_CHANGED = "EXTENSION_MAPPING_CHANGED"
VIEW_RESOLUTION_RECORDED = "VIEW_RESOLUTION_RECORDED"
SOURCE_STATE_CONFLICT = "SOURCE_STATE_CONFLICT"
UNRESOLVED = "UNRESOLVED"

ALL = frozenset(v for k, v in globals().items()
                if k.isupper() and isinstance(v, str))


def transition(kind: str, filing_id: str, **detail) -> dict:
    assert kind in ALL, f"unknown transition {kind}"
    return {"transition": kind, "filing_id": filing_id,
            **{k: v for k, v in sorted(detail.items())}}
