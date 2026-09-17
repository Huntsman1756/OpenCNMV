"""Observation document contract for incremental updates (G2-D).

An *observation* is the canonical projection of one authoritative capture:
what the CNMV source state says now, expressed in Canonical Model V1
terms. Capture/discovery produces it (offline-preserved evidence +
production canonicalize primitives); classify/apply consume it fully
offline. The update engine never fetches.

Document shape (canonical JSON):

  {
    "observation_format": "CANONICAL_OBSERVATION_V1",
    "observation_id":     "obs:<slug>",
    "captured_at":        ISO-8601 string or null,
    "filings": [
      {
        "filing":          <canonical filing object (G1-E fx shape)>,
        "extras":          <dict | null>   — non-schema overlay fields
                           (fixture-faithful extras; absence of a key
                           means "unchanged", so replay is idempotent),
        "extra_artifacts": [{"event_id": ..., "artifact": {...}}]
                           — artifacts owned by version_events,
        "states": [
          {"state_id": ..., "variant_version_id": ...,
           "facts": [canonical fact records],   // or "facts_path" +
           "units": [{"num": [...], "den": [...]}],  // "units_path"
           "provenance": {...provenance row fields...}}
        ],
        "extension_mapping_files": [
          {"source_file": ..., "source_lang": "es", "target_lang": "en",
           "records": [raw G1-C-style records]}
        ],
        "artifact_dispositions": {
          "<artifact_id>": {"status": "REMOVED_CONFIRMED",
                            "evidence": "<reference>"}
        }
      }
    ]
  }

Rules:
  * `filing` is the COMPLETE observed canonical object for that filing —
    including all still-valid history. Rows present in the dataset but
    absent from the observation are treated as removal claims and
    classified conservatively (UNRESOLVED) unless evidence is attached.
  * `states` carries fact records only for variant_versions the
    observation introduces. Facts for an already-recorded version are
    never re-supplied (replay must be a no-op).
  * observation_id/captured_at are capture metadata; the semantic hash is
    computed over the filings payload only, so re-capturing identical
    source state with a new timestamp still replays identically.
"""
from __future__ import annotations

import hashlib
import json

from opencnmv.provenance.hashes import canon

OBSERVATION_FORMAT = "CANONICAL_OBSERVATION_V1"

REQUIRED_FILING_KEYS = ("filing_id", "issuer", "registro_oficial",
                        "family", "period_end", "filing_versions",
                        "submission_variants", "view_resolutions",
                        "version_events", "extension_mappings")


class ObservationError(ValueError):
    """Malformed or self-inconsistent observation document."""


def validate(obs: dict) -> list[str]:
    """Structural validation; returns a list of problems ([] = ok)."""
    err: list[str] = []
    if obs.get("observation_format") != OBSERVATION_FORMAT:
        err.append(f"observation_format != {OBSERVATION_FORMAT}")
    if not obs.get("observation_id"):
        err.append("missing observation_id")
    filings = obs.get("filings")
    if not isinstance(filings, list) or not filings:
        err.append("filings must be a non-empty list")
        return err
    for i, fo in enumerate(filings):
        fx = fo.get("filing")
        if not isinstance(fx, dict):
            err.append(f"filings[{i}]: missing filing object")
            continue
        for k in REQUIRED_FILING_KEYS:
            if k not in fx:
                err.append(f"filings[{i}].filing: missing {k!r}")
        vvids = {vv["variant_version_id"]
                 for sv in fx.get("submission_variants", [])
                 for vv in sv.get("variant_versions", [])}
        for j, st in enumerate(fo.get("states", [])):
            if st.get("variant_version_id") not in vvids:
                err.append(f"filings[{i}].states[{j}]: variant_version_id "
                           f"{st.get('variant_version_id')!r} not in filing")
            if st.get("facts") is None and st.get("facts_path") is None:
                err.append(f"filings[{i}].states[{j}]: no facts payload")
            prov = st.get("provenance")
            if not isinstance(prov, dict) or not prov.get("sha256"):
                err.append(f"filings[{i}].states[{j}]: no provenance")
        for j, ea in enumerate(fo.get("extra_artifacts", [])):
            ev = ea.get("event_id")
            if ev not in {e["event_id"] for e in fx.get("version_events",
                                                       [])}:
                err.append(f"filings[{i}].extra_artifacts[{j}]: event_id "
                           f"{ev!r} not in filing.version_events")
            if not ea.get("artifact", {}).get("sha256"):
                err.append(f"filings[{i}].extra_artifacts[{j}]: "
                           "artifact missing sha256")
    return err


def observation_sha256(obs: dict) -> str:
    """Semantic hash over the filings payload (excludes capture metadata).

    Re-capturing identical source state with a different observation_id /
    captured_at yields the same semantic hash — replay is a no-op.
    """
    return hashlib.sha256(canon(obs["filings"]).encode("utf-8")).hexdigest()


def verify_self_consistency(obs: dict) -> None:
    """If the document carries a pinned semantic hash, enforce it."""
    pinned = obs.get("observation_sha256")
    if pinned is not None and pinned != observation_sha256(obs):
        raise ObservationError(
            f"observation_sha256 mismatch: pinned {pinned} != "
            f"computed {observation_sha256(obs)}")
    problems = validate(obs)
    if problems:
        raise ObservationError("invalid observation: "
                               + "; ".join(problems[:8]))


def load(path) -> dict:
    obs = json.loads(open(path, encoding="utf-8-sig").read())
    verify_self_consistency(obs)
    return obs
