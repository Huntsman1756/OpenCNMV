# R1 — SOURCE_DISCOVERY_EXACT

**Gate:** R1 — SOURCE_DISCOVERY_EXACT
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC 22:15) — resolution session
**Reason for PASS:** Exact corpus enumeration → artefact is now demonstrated end-to-end for SAN,
BBVA and IBE via the per-entity GET path (`listaifi?nif=` for IPP, `ListadoIFA?nif=` for ESEF).
Every target slot (H1-2024…H1-2026; FY2024, FY2025) is enumerated with a stable `nreg` / `registro
oficial`, and each resolves to a stable, byte-deterministic raw XBRL/ iXBRL artefact.

## Objective

Demonstrate how to locate exactly the CNMV filings for the frozen corpus
(SAN / BBVA / IBE; IFA–ESEF FY2024–FY2025, IPP quarters/semesters).

## Source families identified (CNMV official surfaces)

| Source family | Entrypoint | Discovery identifiers | Evidence |
|---|---|---|---|
| IFA / Annual financial reports (cuentas anuales, incl. ESEF) | `…/portal/consultas/em_inffinanual.aspx?id=EE` → routes to `…/portal/consultas/busqueda.aspx?id=25` ("Registro Oficial de las cuentas anuales") | registry `id=25`, entity denomination, date range, last-N-days | `evidence/em_inffinanual`, `evidence/busqueda-id25*` |
| Interim / IPP (información financiera intermedia) | `…/portal/consultas/busqueda.aspx?id=6` | registry `id=6` | `evidence/busqueda-id6-bbva.html` |
| IPP XBRL viewer & download | `…/ipps/default.aspx` (separate ASP.NET AJAX app, tabs Visualización/Descarga, "Buscar por: Ibex 35 / Sector / Entidades emisoras") | app-specific | `evidence/ipps-default.html` |
| IPP taxonomies (CNMV-owned) | `…/xbrl/xbrl` | Circular → `/IPP/taxonomia/<version>/ipp_<version>.zip` | `evidence/xbrl-index.html` |
| Raw artefact download webservice | `https://www.cnmv.es/webservices/verdocumento/ver?t=%7b<guid>%7d` | GUID | `evidence/homepage.html` |
| Per-entity aggregated registry | `…/portal/consultas/datosentidad.aspx?nif=<NIF>` | NIF | `evidence/datosentidad-bbva.*` |
| Entity sitemap | `…/portal/Search/Sitemap/sitemap_entidades.xml` | partial NIF/code list | `evidence/sitemap_entidades.xml` |

## Issuer identity (R1/R5 groundwork)

| Ticker | Legal name found | Registry key | Confirmed via |
|---|---|---|---|
| SAN | **BANCO SANTANDER, S.A.** | `nif=A39000013` | `datosentidad.aspx?nif=A39000013` |
| BBVA | **BANCO BILBAO VIZCAYA ARGENTARIA, S.A.** | `nif=A48265169` | `datosentidad.aspx?nif=A48265169` |
| IBE | **IBERDROLA, S.A.** | `nif=A-48010615` · `LEI=5QK37QC7NWOJ8D7WVQ45` | `ListadoIFA?nif=A-48010615` / `listaifi?nif=A-48010615` |

## Discovery flow (proven, reproducible)

The **preferred** path is the per-entity GET enumeration (no WebForms browser needed).

- **IPP:** `…/portal/consultas/ifi/listaifi?lang=es&nif=<NIF>` → per-row stable `nreg`
  → `…/portal/aldia/detalleifialdia.aspx?nreg=<nreg>` → "Informe completo en formato"
  → `…/portal/consultas/wuc/descargaxbrlipp.ashx?t={GUID}` (ephemeral) → **redirect** →
  `webservices/verdocumento/ver?e=<token>` (stable) → raw XBRL.
- **ESEF:** `…/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif=<NIF>` → per-row `registro
  oficial` → `webservices/verdocumento/ver?e=<token>` → iXBRL XHTML.
- **Taxonomies (CNMV-owned):** `…/xbrl/xbrl` → `/IPP/taxonomia/<version>/ipp_<version>.zip`
  (Circulars 3/2018, 5/2015, 1/2008, 1/2005).

## Findings (enumeration results)

- **IPP `nreg` per issuer (corpus slots):**
  - SAN: H1-2026 `2026103368`, H2-2025 `2026029523`, H1-2025 `2025106044`, H2-2024 `2025031125`,
    H1-2024 `2024098684`.
  - BBVA: H1-2026 `2026109500`, H2-2025 `2026023406`, H1-2025 `2025106553`, H2-2024 `2025023010`,
    H1-2024 `2024102594`.
  - IBE: H1-2026 `2026103709`, H2-2025 `2026031470`, H1-2025 `2025101457`, H2-2024 `2024099131`,
    H1-2024 `2024027902`.
- **ESEF `registro oficial`:** SAN FY2025 `20875`/FY2024 `20509`; BBVA FY2025 `20854`/FY2024
  `20448`; IBE FY2025 `20934`/FY2024 `20515`.
- Each issuer exposes 60 IPP `nreg` and 18 ESEF `?e=` artefact links.

## Limitation (identity caveat)

The IPP `?t={GUID}` intermediate in the detail page is **ephemeral** (changes per visit), but it
always redirects to the **same stable `?e=` token** and the **same bytes** (verified: two different
GUIDs for the same `nreg` returned identical SHA-256). Therefore the canonical identity must use
the stable `nreg` (IPP) / `registro oficial` (ESEF) as `source_registration_no`, and resolve the
stable `?e=` token via discovery; **never** use `?t={GUID}` as identity.

## Evidence

- `evidence/listaifi-IBE.html`, `evidence/listaifi-SAN.html`, `evidence/listaifi-BBVA.html`
- `evidence/ListadoIFA-IBE.html`, `evidence/ListadoIFA-SAN.html`, `evidence/ListadoIFA-BBVA.html`
- `evidence/detalleifialdia-IBE-H1-2026.html`, `…-SAN-…`, `…-BBVA-…`
- (earlier) `evidence/em_inffinanual`, `evidence/busqueda-id25*`, `evidence/xbrl-index.html`,
  `evidence/ipps-default.html`, `evidence/datosentidad-bbva.*`, `evidence/homepage.html`
