# R7 — RAW_ARTIFACT_RETRIEVAL

**Gate:** R7 — RAW_ARTIFACT_RETRIEVAL
**Status:** `PASS` (remediated)
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`

> Remediation note: R9 showed the original 6 ESEF artefacts were the **Portada/cover** (no
> `ix:`/`schemaRef`). The corpus raw is now complete: 15 IPP + 6 **ESEF_COVER** + 6
> **ESEF_PACKAGE_ZIP_XBRL** (self-contained: iXBRL + issuer extension taxonomy + META-INF). The
> real iXBRL is preserved inside the ZIP packages; its standalone XHTML is too large to store as a
> repo file but its SHA/schemaRef are recorded in `esef_components.json`.

## Objective

Download the original artefacts for the frozen corpus without re-serialising, recording
`source_url`, `retrieved_at`, HTTP metadata, `media_type`, `byte_size`, plus
`source_registration_no`.

## Method

`download_corpus.ps1` performs, per issuer (SAN / BBVA / IBE):
- **IPP:** `listaifi?nif=` → `nreg` (per period) → `detalleifialdia?nreg=` →
  `descargaxbrlipp.ashx?t={GUID}` (ephemeral) → redirect → `ver?e=` → raw XBRL.
- **ESEF:** `ListadoIFA?nif=` → per row (`registro oficial`): `ver?e=<token>` per component —
  Individual (serves the **Portada/cover** XHTML), Consolidada (**real iXBRL**), ZIP/Xbri
  (**ESEF package**). Components enumerated in `esef_components.json` / `esef_packages.json`.

Bytes are written **as received** (no re-serialisation); metadata recorded into
`artifact_manifest.json`.

## Result

**27 raw artefacts** retrieved — 21 filings ≠ 21 artefacts; each ESEF filing has several
components:

| Family | Role | Slots | Media type | Issuers |
|---|---|---|---|---|
| IPP | `IPP_XBRL` | H1-2024, H2-2024, H1-2025, H2-2025, H1-2026 | `text/xml` | SAN, BBVA, IBE |
| ESEF | `ESEF_COVER` (Portada) | FY2024, FY2025 | `application/xhtml+xml` | SAN, BBVA, IBE |
| ESEF | `ESEF_PACKAGE_ZIP_XBRL` (iXBRL + extension taxonomy + META-INF) | FY2024, FY2025 | `application/zip` | SAN, BBVA, IBE |

The 6 `IXBRL_CONSOLIDATED` standalone reports (28–118 MB) were fetched twice and verified
byte-stable (`sha256_run1 == sha256_run2` in `esef_components.json`); their raw is preserved
inside the ZIP packages.

**Model decision (verified):** the `reports/*.xhtml` member of each `ESEF_PACKAGE_ZIP_XBRL` is
**byte-identical** to the standalone consolidated XHTML served by the direct `?e=` link
(`verify_ixbrl_member.ps1` → `ixbrl_member_equality.json`, 6/6 `byte_equal=true`). Therefore
`IXBRL_CONSOLIDATED` is **not** a separately persisted artefact: it is modelled as
*package member + direct CNMV view* of the same bytes. Persisted inventory stays **27**; the
member path + member SHA-256 + equality flag are recorded both in `esef_components.json`
(`IXBRL_CONSOLIDATED` rows) and in `artifact_manifest.json` (`ESEF_PACKAGE_ZIP_XBRL` rows).

`artifact_manifest.json` per artefact records: `role`, `family`, `source_registration_no`
(`nreg` / `registro`), `source_url`, `final_url` (after redirect), `retrieved_at`, `http_status`,
`media_type`, `byte_size`, `elapsed_ms`, `set_cookie`, `sha256`, `evidence_path`.

## Findings / observations

- **Both families retrieve out-of-session, no cookies, no referer** (recorded `set_cookie` empty).
- **IPP H2 vs H1 size asymmetry:** H2 artefacts are notably smaller (e.g. SAN H2-2025 = 392 KB,
  H1-2026 = 31.8 MB). This suggests the H2 XBRL instance differs in structure/content from the H1
  (to be investigated in R9/R12 — taxonomy/model heterogeneity).
- The `?t={GUID}` is ephemeral: a **stored** `?t=` URL re-downloaded later returns EMPTY. A fresh
  GUID (from `nreg` → detail) resolves to the same `?e=` + bytes (see R4/R6/R8).
- `source_registration_no` maps cleanly to `nreg` (IPP) / `registro oficial` (ESEF), feeding the
  `filing`/`filing_version` model.
- **Correction (post-remediation audit):** `esef_components.json` initially recorded the **AUDITA
  column** number (`/AUDITA/<year>/<reg>.pdf` link text) as `registro` — the page-global
  `>(\d{5})<` regex matched the audit-report links, not the registro-oficial cell. Verified
  per-row against the preserved `ListadoIFA` evidence: official registros are SAN 20875/20509,
  BBVA 20854/20448, IBE 20934/20515 (FY2025/FY2024). `esef_components.json` and the
  `ESEF_COVER.source_registration_no` placeholders (`registro-SAN-FY2025`) were corrected
  accordingly. `remediate_esef.ps1` now parses registro + tokens from the same `<tr>`.

## Evidence

- `artifact_manifest.json` (metadata for all 27 artefacts)
- `esef_components.json`, `esef_packages.json` (per-filing component enumeration + schemaRefs)
- `ixbrl_member_equality.json` (package member vs direct `?e=` download, byte-equality proof)
- `evidence/ipp-{SAN,BBVA,IBE}-*.zip`, `evidence/esef-{SAN,BBVA,IBE}-FY*.zip`,
  `evidence/esef-{SAN,BBVA,IBE}-FY*-package.zip`
- `download_corpus.ps1`, `remediate_esef.ps1`, `extract_schemaref.ps1`, `build_inventory.ps1`,
  `verify_ixbrl_member.ps1`
