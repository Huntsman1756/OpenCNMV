# R8 — RAW_SHA256_STABLE

**Gate:** R8 — RAW_SHA256_STABLE
**Status:** `PASS` (remediated)
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`

> Remediation note: verification now runs on the **complete** corpus inventory. **27/27 MATCH**
> (15 IPP + 6 ESEF_COVER + 6 ESEF_PACKAGE_ZIP_XBRL); the 6 IXBRL_CONSOLIDATED were separately
> verified byte-stable (run1==run2) in the R4 remediation. **Important:** the IPP `?t={GUID}` is
> ephemeral — re-downloading a stored `?t=` URL returns EMPTY; IPP is re-resolved via `nreg` →
> detail → fresh GUID (discovery). This confirms R6 (`nreg` is the stable IPP locator, not the URL).

## Objective

Compute SHA-256 of each raw artefact; a second download must produce the same hash (or demonstrate
the source changed). Never silently overwrite prior bytes.

## Method

`r8_verify.ps1` re-downloads each artefact in `artifact_manifest.json` in a fresh session and
compares the SHA-256 with the run-1 hash recorded in the manifest. ESEF artefacts use the stored
stable `?e=` URL; IPP artefacts are re-resolved via `nreg` → detail → fresh `?t={GUID}` (the
stored `?t=` is ephemeral and returns empty).

## Result

**27 / 27 MATCH**, 0 mismatch, 0 errors — on the complete corpus inventory.

| Role | Count | Result |
|---|---|---|
| IPP_XBRL (`text/xml`) | 15 | all MATCH |
| ESEF_COVER (`application/xhtml+xml`) | 6 | all MATCH |
| ESEF_PACKAGE_ZIP_XBRL (`application/zip`) | 6 | all MATCH |

The 6 `IXBRL_CONSOLIDATED` standalone reports were separately verified byte-stable out-of-session
(run1 == run2) in the R4 remediation (`esef_components.json`), and proven **byte-identical** to
the `reports/*.xhtml` member inside each persisted ZIP package (`ixbrl_member_equality.json`,
6/6 `byte_equal`). They are therefore covered by the 27-artefact persisted inventory as package
members, not counted as separate artefacts.

Full per-artefact comparison in `evidence/sha256_verify.json` (`run1_sha256` vs `run2_sha256`,
`match`).

## Findings

- Every corpus artefact is **byte-stable** on re-download out-of-session.
- The IPP `?t={GUID}` is **ephemeral**: re-downloading a stored `?t=` URL returned **EMPTY**.
  IPP artefacts are re-resolved via `nreg` → detail → fresh GUID (discovery); the fresh GUID
  yields the same bytes. This confirms R6: `nreg` is the stable IPP locator, not the URL.
- No source drift detected in this window.

## Limitation

This verifies stability within a single session window (~tens of minutes). Long-horizon drift (the
source replacing a file over weeks/months) is the responsibility of ongoing R8 monitoring (re-run
this verification periodically; a changed hash ⇒ the source changed ⇒ flag, never overwrite).

## Evidence

- `evidence/sha256_verify.json` (run1 vs run2 SHA-256 per artefact)
- `g0-r/R07-raw-retrieval/artifact_manifest.json` (run-1 hashes)
- `r8_verify.ps1`
