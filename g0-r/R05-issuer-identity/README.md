# R5 — ISSUER_IDENTITY_EXACT

**Gate:** R5 — ISSUER_IDENTITY_EXACT
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`

## Objective

Demonstrate unambiguous identity for SAN, BBVA, IBE. Separate `issuer`, `issuer_identifier`,
`security`. Do **not** make ISIN the primary issuer identity.

## Result (NIF ↔ legal entity ↔ LEI)

| Ticker | issuer (legal entity, CNMV) | issuer_identifier (NIF) | issuer_identifier (LEI) | GLEIF status |
|---|---|---|---|---|
| SAN | BANCO SANTANDER, S.A. | `A39000013` | `5493006QMFDDMYWIAM13` | ACTIVE |
| BBVA | BANCO BILBAO VIZCAYA ARGENTARIA, S.A. | `A48265169` | `K8MS7FD7N5Z2WQ51AZ71` | ACTIVE (jurisdiction ES) |
| IBE | IBERDROLA, S.A. | `A-48010615` | `5QK37QC7NWOJ8D7WVQ45` | ACTIVE |

- **CNMV source (authoritative for the registry key):** `datosentidad.aspx?nif=<NIF>` returns the
  exact legal entity name (evidence: `cnmv_datosentidad_*.html`).
- **LEI source (authoritative for LEIs):** GLEIF `api/v1/lei-records?filter[lei]=<LEI>` →
  ACTIVE, legal name matches the CNMV legal entity (evidence: `gleif_*.json`).
- The NIF↔LEI mapping is established by legal entity name + jurisdiction match.

## issuer vs issuer_identifier vs security

```text
issuer            = the legal entity (name). Identified by NIF (CNMV) and LEI (GLEIF).
issuer_identifier = NIF, LEI — identifiers OF the issuer.
security          = a specific listed security (e.g. a share class / ISIN), distinct from the issuer.
```

- A single issuer can have **multiple securities** (different share classes, bonds, etc.).
- **ISIN identifies a security, not the issuer.** It must not be used as the primary issuer
  identity. (The CNMV registry key is the NIF; the issuer's LEI is the global entity identifier.)
- For the frozen corpus, the issuer is the Spanish parent entity (SAN/BBVA/IBE), each with a
  distinct NIF + LEI; subsidiaries/branches (e.g. BBVA Colombia, BBVA Uruguay, IBERDROLA France)
  were explicitly excluded from identity.

## Note on GLEIF filtering

`filter[entity.legalName]` works only with a clean name (no trailing comma/period); with
punctuation the API silently returned the full dataset. `filter[lei]` returns exactly one record.
Both used for evidence.

## Evidence

- `evidence/cnmv_datosentidad_SAN.html`, `_BBVA.html`, `_IBE.html` (+ `.txt`) — CNMV NIF → legal name
- `evidence/gleif_5493006QMFDDMYWIAM13.json`, `gleif_K8MS7FD7N5Z2WQ51AZ71.json`,
  `gleif_5QK37QC7NWOJ8D7WVQ45.json` — GLEIF LEI → name/status/jurisdiction
- Cross-check: SAN LEI also present in the issuer's own ESEF FY2025 filing (`?e=` artefact).
