# R8 — RAW_SHA256_STABLE

**Gate:** R8 — RAW_SHA256_STABLE
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`

## Objective

Compute SHA-256 of each raw artefact; a second download must produce the same hash (or demonstrate
the source changed). Never silently overwrite prior bytes.

## Method

`r8_verify.ps1` re-downloads each artefact in `artifact_manifest.json` (same `source_url`) in a
fresh session and compares the SHA-256 with the run-1 hash recorded in the manifest.

## Result

**21 / 21 MATCH**, 0 mismatch, 0 errors.

| Family | Count | Result |
|---|---|---|
| IPP (text/xml) | 15 | all MATCH |
| ESEF (application/xhtml+xml) | 6 | all MATCH |

Full per-artefact comparison in `evidence/sha256_verify.json` (`run1_sha256` vs `run2_sha256`,
`match`).

## Findings

- Every corpus artefact is **byte-stable** on re-download out-of-session.
- Re-download of the IPP `descargaxbrlipp.ashx?t={GUID}` (ephemeral GUID) still yields the same
  bytes as run 1 — confirming the `?t=` resolves deterministically to the same `?e=` + bytes.
- No source drift detected in this window.

## Limitation

This verifies stability within a single session window (~tens of minutes). Long-horizon drift (the
source replacing a file over weeks/months) is the responsibility of ongoing R8 monitoring (re-run
this verification periodically; a changed hash ⇒ the source changed ⇒ flag, never overwrite).

## Evidence

- `evidence/sha256_verify.json` (run1 vs run2 SHA-256 per artefact)
- `g0-r/R07-raw-retrieval/artifact_manifest.json` (run-1 hashes)
- `r8_verify.ps1`
