# STATUS.md — OpenCNMV session status

> **Operational state only.** This file records current gates, checkpoint, blocking findings and
> next action. It is **not** the source of truth for criteria. The authority for gates, corpus,
> scope and acceptance criteria is `AGENTS.md` + `docs/gates/G0-R.md` (+ `docs/PROJECT.md` for the
> model). Never edit this file first to change a criterion; decide gate verdicts against
> `docs/gates/G0-R.md`.

Update at the end of every session.

## Current phase

**G0-R** (CNMV Source & Reproducibility Probe) — R0–R4 closed; R0–R4 checkpoint `CONTINUE`.

## Gate statuses

```text
R0  PASS    # legal reuse
R1  PASS    # exact corpus enumeration -> artefact proven via listaifi/ListadoIFA (SAN/BBVA/IBE)
R2  PASS    # access mechanism characterised (use per-entity GET path; bypass general WebForms postback)
R3  PASS    # discovery stable across two observations (+ ListadoIFA byte-identical, ?e= tokens stable)
R4  FAIL    # REOPENED by R9: the six 'ESEF iXBRL' artefacts tested were the Portada/cover, not iXBRL
R5  PASS    # issuer identity: NIF <-> legal entity <-> LEI, issuer != security (SAN/BBVA/IBE)
R6  PASS    # source filing key: nreg/registro = logical filing (best observed); substitution persistence NOT_YET_PROVEN -> R13
R7  FAIL    # REOPENED by R9: ESEF corpus raw incomplete (only covers); real iXBRL + ZIP/Xbri missing
R8  FAIL    # REOPENED by R9: 21/21 stable but inventory incomplete (missing ESEF iXBRL + ZIP/Xbri)
R9  FAIL    # own finding: FY2024 ESEF taxonomy inferred as 'analogous', not observed; real iXBRL not analysed
R10-R17  NOT_RUN
```

## Checkpoint

```text
R0–R4 CHECKPOINT: HOLD   (reopened by R9 new evidence: ESEF artefact misclassification)
```

`CONTINUE` would authorise proceeding to R5; it is restored only after the R4/R7/R8/R9 remediation
(real ESEF iXBRL + ZIP/Xbri enumerated, downloaded, byte-stable, and taxonomy-observed incl. FY2024).
**G1 is not touched** until the final G0-R verdict (after R17) is `GO`.

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

## Session-2 findings (R5–R8)

- **R5 PASS:** identity = issuer (legal entity) + identifiers (NIF, LEI); issuer != security.
  SAN=NIF A39000013/LEI 5493006QMFDDMYWIAM13; BBVA=A48265169/K8MS7FD7N5Z2WQ51AZ71;
  IBE=A-48010615/5QK37QC7NWOJ8D7WVQ45.
- **R6 PASS:** `nreg` (IPP) / `registro oficial` (ESEF) identify the logical filing
  (`source_registration_no`), stable across substitutions; `?e=` = per-version locator;
  `?t={GUID}` = ephemeral transport (never identity). No in-corpus substitution present to
  falsify against; semantics taken from the source legend.
- **R7 PASS:** 21 raw corpus artefacts materialized (15 IPP `text/xml` + 6 ESEF `application/xhtml+xml`)
  with HTTP metadata + `source_registration_no`. Observed: IPP H2 artefacts are much smaller than H1
  (potential model/taxonomy heterogeneity for R9/R12).
- **R8 PASS:** 21/21 artefacts byte-stable on re-download (SHA-256 match).
- **R9 PASS:** taxonomy discovery. IPP = 2019-01-01 (Circular 3/2018), model `ipp_en` (SAN/BBVA,
  credit) vs `ipp_ge` (IBE, general); H1/H2 same taxonomy (size = facts). ESEF iXBRL references an
  issuer extension taxonomy (santander.com / bbva.es / iberdrola.com, `20251231`) + ESMA base;
  the R7 ESEF artefacts are cover-only (no ix:/schemaRef); the ZIP/Xbri package (extension
  taxonomy) is a required dependency -> feeds R10.
- **R6 caveat:** `nreg`/`registro` = best observed `source_registration_no` (unique + stable across
  observations); **stability across a real substitution = NOT_YET_PROVEN, deferred to R13.**
- **R9 finding (reopens R4/R7/R8):** the six ESEF artefacts downloaded in R7 (and hash-tested in R8,
  and claimed as iXBRL in R4) are the **Portada (cover)** XHTML — **no `ix:`/`schemaRef`**. The real
  inline-XBRL report and the ZIP/Xbri package are **separate components** in the same `ListadoIFA`
  row. So R4/R7/R8's ESEF claim was misclassified; the inventory was incomplete.
- **Model insight:** 21 filings ≠ 21 artefacts. An ESEF filing has multiple artefacts:
  `COVER`, `IXBRL_CONSOLIDATED`, `IXBRL_INDIVIDUAL` (if applicable), `ESEF_PACKAGE_ZIP_XBRL`.
- **R17 finding (recorded, not executed):** SAN H2-2025 IPP contains `Dcur_PeriodoCorrienteActualMiembro`
  (2025-07-01→2025-12-31) and `Dcur_AcumuladoActualMiembro` (2025-01-01→2025-12-31) — same period_end,
  different temporal semantics (see `docs/findings/0002-*.md`).

## Blocking findings

- None for the R0–R4 checkpoint. Long-horizon token/URL drift is monitored by re-running the R8
  verification periodically.

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

Proceed to **R10** (within G0-R), following `AGENTS.md` and `docs/gates/G0-R.md`:
`R10 TAXONOMY_PINNING → R11/R12 Arelle parse → R13 revisions → R14/R15 determinism → R16 oracle
reconciliation → R17 H2 vs ESEF`. Do **not** build product, UI, API, or MCP. G1 is not touched until
R17 is closed.

## Session hygiene

- Update this file at the end of every session.
- Prefer small, explicit dependencies. Do not build general infrastructure.
