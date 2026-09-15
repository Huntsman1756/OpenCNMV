# STATUS.md — OpenCNMV session status

> **Operational state only.** This file records current gates, checkpoint, blocking findings and
> next action. It is **not** the source of truth for criteria. The authority for gates, corpus,
> scope and acceptance criteria is `AGENTS.md` + `docs/gates/G0-R.md` (+ `docs/PROJECT.md` for the
> model). Never edit this file first to change a criterion; decide gate verdicts against
> `docs/gates/G0-R.md`.

Update at the end of every session.

## Current phase

**G0-R** (CNMV Source & Reproducibility Probe) — session 1 complete (R0–R4).

## Gate statuses

```text
R0  PASS    # legal reuse
R1  FAIL    # exact corpus enumeration -> artefact not yet proven
R2  PASS    # access mechanism characterised (critical finding: general registry postback returns 0 rows)
R3  PASS    # discovery stable across two observations
R4  FAIL    # target artefact families (ESEF iXBRL, IPP XBRL) not both proven
R5-R17  NOT_RUN
```

## Checkpoint

```text
CHECKPOINT: HOLD
```

## Blocking findings

- **R1:** exact corpus enumeration not demonstrated. A per-entity GET path
  (`listaifi?nif=` / `ListadoIFA?nif=`) was identified post-session and is the candidate to
  resolve this; it is still unproven.
- **R4:** `ARTIFACT_URL_STABILITY` proven only for one generic GUID artefact + one taxonomy ZIP.
  The two corpus families are untested. The ESEF consolidated iXBRL may use
  `webservices/verdocumento/ver?e=<opaque-token>` (variant to test). If `?e=` changes per visit
  while returning the same bytes, R4 stays FAIL and canonical identity must not rely on the URL.

## Corrected corpus (accepted this session)

```text
SAN / BBVA / IBE

ESEF
  FY2024
  FY2025

IPP
  H1-2024  H2-2024
  H1-2025  H2-2025
  H1-2026
```

Q1/Q3 ≥ 2021-05-03 → `NOT_REQUIRED_AS_IPP` (not `NOT_FOUND`). Voluntary quarterly → `OUT_OF_SCOPE_G0`.

## Issuer identity (fixed)

```text
SAN  BANCO SANTANDER, S.A.                 nif=A39000013
BBVA BANCO BILBAO VIZCAYA ARGENTARIA, S.A. nif=A48265169
IBE  IBERDROLA, S.A.                       nif=A-48010615  LEI=5QK37QC7NWOJ8D7WVQ45
```

## Next action

Resolve R1 and R4 only. Do **not** advance to R5.

1. Freeze IBE identity (above).
2. Probe GET enumeration `listaifi?nif=...` and `ListadoIFA?nif=...` for SAN, BBVA, IBE.
3. IPP end-to-end: `NIF → nreg → XBRL GUID`; download twice out-of-session; compare SHA-256.
4. ESEF end-to-end: `NIF → registro oficial → consolidated iXBRL`; inspect `?e=` token; download
   twice out-of-session; compare SHA-256.
5. Repeat discovery; compare `nreg`, GUID / `e`-token, and final bytes.
6. Re-evaluate R1 and R4; update `docs/STATUS.md`.

## Session hygiene

- Update this file at the end of every session.
- Prefer small, explicit dependencies. Do not build general infrastructure.
