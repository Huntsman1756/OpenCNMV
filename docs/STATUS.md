# STATUS.md — OpenCNMV session status

> **Operational state only.** This file records current gates, checkpoint, blocking findings and
> next action. It is **not** the source of truth for criteria. The authority for gates, corpus,
> scope and acceptance criteria is `AGENTS.md` + `docs/gates/G0-R.md` (+ `docs/PROJECT.md` for the
> model). Never edit this file first to change a criterion; decide gate verdicts against
> `docs/gates/G0-R.md`.

Update at the end of every session.

## Current phase

**G0-R** (CNMV Source & Reproducibility Probe) — R0–R4 closed; checkpoint `GO`.

## Gate statuses

```text
R0  PASS    # legal reuse
R1  PASS    # exact corpus enumeration -> artefact proven via listaifi/ListadoIFA (SAN/BBVA/IBE)
R2  PASS    # access mechanism characterised (use per-entity GET path; bypass general WebForms postback)
R3  PASS    # discovery stable across two observations (+ ListadoIFA byte-identical, ?e= tokens stable)
R4  PASS    # IPP raw XBRL + ESEF iXBRL byte-stable out-of-session for SAN/BBVA/IBE
R5-R17  NOT_RUN
```

## Checkpoint

```text
CHECKPOINT: GO
```

`GO` authorises **G1 design**, not a full platform. R5 → R17 still remain within G0-R.

## Resolution-session findings (R1/R4)

- **R1 PASS:** exact enumeration proven for all three issuers:
  - IPP (`listaifi?nif=`): stable `nreg` per period; SAN/BBVA/IBE each expose 60 `nreg`, including
    the corpus slots H1-2024…H1-2026.
  - ESEF (`ListadoIFA?nif=`): stable `registro oficial`; SAN FY2025=20875/FY2024=20509,
    BBVA FY2025=20854/FY2024=20448, IBE FY2025=20934/FY2024=20515.
- **R4 PASS:** both families byte-stable out-of-session for all three issuers (identical SHA-256
  across repeated downloads). The 18 ESEF `?e=` tokens are identical between visits.
- **Critical model rule:** the IPP `?t={GUID}` is **ephemeral** (changes per visit) but always
  redirects to the same stable `?e=` token and the same bytes. Canonical identity must use `nreg`
  (IPP) / `registro oficial` (ESEF) as `source_registration_no`; **never** `?t={GUID}`.

## Blocking findings

- None for the R0–R4 checkpoint. Long-horizon token/URL drift is deferred to R8
  (RAW_SHA256_STABLE).

## Corrected corpus (accepted)

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

Proceed to **R5** (within G0-R), following `AGENTS.md` and `docs/gates/G0-R.md`:
`R5 ISSUER_IDENTITY_EXACT → R6 SOURCE_FILING_KEY_STABLE → R7 RAW_ARTIFACT_RETRIEVAL → R8
RAW_SHA256_STABLE → R9/R10 taxonomy → R11/R12 Arelle parse → R13 revisions → R14/R15 determinism →
R16 oracle reconciliation → R17 H2 vs ESEF`. Do **not** build product, UI, API, or MCP.

## Session hygiene

- Update this file at the end of every session.
- Prefer small, explicit dependencies. Do not build general infrastructure.
