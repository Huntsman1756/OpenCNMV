# R7 — RAW_ARTIFACT_RETRIEVAL

**Gate:** R7 — RAW_ARTIFACT_RETRIEVAL
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`

## Objective

Download the original artefacts for the frozen corpus without re-serialising, recording
`source_url`, `retrieved_at`, HTTP metadata, `media_type`, `byte_size`, plus
`source_registration_no`.

## Method

`download_corpus.ps1` performs, per issuer (SAN / BBVA / IBE):
- **IPP:** `listaifi?nif=` → `nreg` (per period) → `detalleifialdia?nreg=` →
  `descargaxbrlipp.ashx?t={GUID}` (ephemeral) → redirect → `ver?e=` → raw XBRL.
- **ESEF:** `ListadoIFA?nif=` → `registro oficial` → `ver?e=<token>` → iXBRL XHTML.

Bytes are written **as received** (no re-serialisation); metadata recorded into
`artifact_manifest.json`.

## Result

**21 raw artefacts** retrieved (15 IPP + 6 ESEF), one per corpus slot:

| Family | Slots | Media type | Issuers |
|---|---|---|---|
| IPP | H1-2024, H2-2024, H1-2025, H2-2025, H1-2026 | `text/xml` | SAN, BBVA, IBE |
| ESEF | FY2024, FY2025 | `application/xhtml+xml` | SAN, BBVA, IBE |

`artifact_manifest.json` per artefact records: `role`, `family`, `source_registration_no`
(`nreg` / `registro`), `source_url`, `final_url` (after redirect), `retrieved_at`, `http_status`,
`media_type`, `byte_size`, `elapsed_ms`, `set_cookie`, `sha256`, `evidence_path`.

## Findings / observations

- **Both families retrieve out-of-session, no cookies, no referer** (recorded `set_cookie` empty).
- **IPP H2 vs H1 size asymmetry:** H2 artefacts are notably smaller (e.g. SAN H2-2025 = 392 KB,
  H1-2026 = 31.8 MB). This suggests the H2 XBRL instance differs in structure/content from the H1
  (to be investigated in R9/R12 — taxonomy/model heterogeneity).
- The `?t={GUID}` is ephemeral but always resolves to the same `?e=` + bytes (see R4/R6).
- `source_registration_no` maps cleanly to `nreg` (IPP) / `registro oficial` (ESEF), feeding the
  `filing`/`filing_version` model.

## Evidence

- `artifact_manifest.json` (metadata for all 21 artefacts)
- `evidence/ipp-{SAN,BBVA,IBE}-*.zip`, `evidence/esef-{SAN,BBVA,IBE}-FY*.zip`
- `download_corpus.ps1`
