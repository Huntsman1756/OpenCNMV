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
R4  PASS    # ARTIFACT_URL_STABILITY (remediated): real ESEF iXBRL + ZIP package + IPP byte-stable out-of-session; IPP ?t={GUID} ephemeral, nreg is the stable locator
R5  PASS    # issuer identity: NIF <-> legal entity <-> LEI, issuer != security (SAN/BBVA/IBE)
R6  PASS    # source filing key: nreg/registro = logical filing (best observed); substitution persistence NOT_YET_PROVEN -> R13
R7  PASS    # RAW_ARTIFACT_RETRIEVAL (remediated): 27 raw artefacts (15 IPP + 6 ESEF_COVER + 6 ESEF_PACKAGE_ZIP_XBRL); components enumerated
R8  PASS    # RAW_SHA256_STABLE (remediated): 27/27 MATCH on complete inventory; IPP re-resolved via nreg
R9  PASS    # TAXONOMY_DISCOVERY (remediated): IPP 2019-01-01 (ipp_en vs ipp_ge); ESEF FY2024+FY2025 schemaRefs observed; SAN domain changed
R10-R17  NOT_RUN
```

## Checkpoint

```text
R0–R4 CHECKPOINT: CONTINUE
```

`CONTINUE` authorises proceeding to **R5** (within G0-R). **G1 is not touched** until the final
G0-R verdict (after R17) is `GO`. The final verdict states are `GO` / `CONDITIONAL_GO` / `NO_GO`.

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

## Remediation (R4/R7/R8/R9) — after the R9 reopening

- Enumerated all ESEF components per filing (Individual / Consolidada / ZIP-Xbri / Informe especial).
- Added 6 ESEF_PACKAGE_ZIP_XBRL (self-contained: iXBRL + issuer extension taxonomy + META-INF), ~10-34MB, SHA-256 recorded.
- The 6 IXBRL_CONSOLIDATED (real inline-XBRL) are byte-stable out-of-session (run1==run2); raw preserved inside the ZIP packages (standalone XHTML too large to store as a repo file).
- Reclassified the 6 covers as ESEF_COVER (hashes/provenance preserved).
- **Key finding:** the IPP `?t={GUID}` is ephemeral — re-downloading a stored `?t=` URL returns EMPTY. IPP must be re-resolved via `nreg` → detail → fresh GUID (discovery). Confirms R6 (`nreg` is the stable locator, not the URL).
- **SAN extension taxonomy domain changed** between years (santanderbank.com FY2024 → santander.com FY2025).
- R8 now verifies 27/27 MATCH on the complete inventory.
- **Post-remediation audit fixes (evidence consistency):**
  - `esef_components.json` `registro` corrected — the scraper's page-global `>(\d{5})<` had captured the **AUDITA column** (audit-report numbers: 18359/17877…), not the registro oficial. Verified per-row against preserved `ListadoIFA` evidence: SAN 20875/20509, BBVA 20854/20448, IBE 20934/20515. `remediate_esef.ps1` now parses registro+tokens from the same `<tr>`.
  - `ESEF_COVER.source_registration_no` placeholders (`registro-SAN-FY2025`) corrected to the official registro in `artifact_manifest.json` and `sha256_verify.json`.
  - `taxonomy_matrix.json` regenerated over the 27-artifact inventory (covers `XHTML_COVER_ONLY`; packages `ESEF_ZIP_PACKAGE` with `has_ix`/`schemaRef` observed inside each ZIP). FY2024 schemaRefs observed, not "analogous".
  - R4 evidence files renamed: `esef-IBE-consolidated_run*.zip` etc. contained the **cover**, now `esef-*-cover_run*.zip`.
- **Artifact model decision (verified):** the `reports/*.xhtml` member inside each ESEF ZIP package is **byte-identical** to the standalone consolidated XHTML served by the direct `?e=` link (`ixbrl_member_equality.json`, 6/6). So `IXBRL_CONSOLIDATED` = *package member + direct CNMV view*, not a separately persisted artefact; persisted inventory stays **27** (`package_member_path`/`member_sha256`/`byte_equal` recorded).

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
