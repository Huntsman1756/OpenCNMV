# R1 — SOURCE_DISCOVERY_EXACT

**Gate:** R1 — SOURCE_DISCOVERY_EXACT
**Status:** `FAIL`
**Executed:** 2026-09-14 (UTC 22:15)
**Reason for FAIL:** The gate requires locating the **exact target filings** for the corpus. In
this session the *surfaces* were identified but exact per-filing enumeration → artefact of the
corpus (SAN/BBVA/IBE, FY2024–FY2025 ESEF, IPP H1/H2 2024–2026) was **not** demonstrated. Per
project rules there is no `mostly-pass`; the gap is a strict `FAIL`, not a `PASS` with a caveat.
A per-entity GET enumeration path (`listaifi?nif=` / `ListadoIFA?nif=`) was identified *after*
the session and is documented in `docs/decisions/0002-*.md` as the candidate to resolve this FAIL.

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
| IBE | IBERDROLA, S.A. | **not resolved** | open — see R5 |

## Discovery flow (documented, reproducible)

1. Resolve the issuer to its NIF (authoritative key) via the entity page or sitemap.
2. For IFA/ESEF: `busqueda.aspx?id=25`; for IPP interim: `busqueda.aspx?id=6`; for IPP
   XBRL download: `/ipps/default.aspx`.
3. Each registry page is an ASP.NET WebForms search by entity denomination / date range /
   last-N-days (see R2).
4. Artefacts are served by `webservices/verdocumento/ver?t={GUID}` or downloaded directly from
   static `/IPP/…` taxonomy paths.

## Findings

- The IFA/ESEF and IPP registries share one parameterised engine (`busqueda.aspx?id=X`).
- Taxonomy versions are versioned by path and are tied to CNMV Circulars (3/2018, 5/2015,
  1/2008, 1/2005) — directly relevant to R9/R10 (taxonomy discovery/pinning).
- The raw-artefact webservice is keyed by a GUID (`%7b<guid>%7d`).

## Limitation (the reason for FAIL): exact corpus retrieval not proven

A bare automated WebForms postback to `busqueda.aspx?id=25` (and `id=6`) with a denomination
(e.g. `IBERDROLA`, `BANCO BILBAO`) **re-renders the search page with 0 result rows** — verified
with two independent HTTP clients (HttpClient and curl). This means the *entrypoints* are
concretely identified, but obtaining the actual result list / artefact GUID for a specific
issuer via this registry requires resolving either:
- the correct postback/session semantics (e.g. an ASP.NET session or JS-driven flow), or
- a different/equivalent surface (e.g. the `/ipps` XBRL download tool, or the IFA per-year
  listing).

This is a **known source-access risk** and is the precise reason the gate is `FAIL`. A per-entity
GET enumeration path was discovered *after* this session and is documented in
`docs/decisions/0002-*.md`:
- **IPP:** `…/portal/consultas/ifi/listaifi?lang=es&nif=<NIF>` → per-row stable `nreg`
  → `…/portal/aldia/detalleifialdia.aspx?nreg=<nreg>` → "Informe completo en formato"
  → `…/portal/consultas/wuc/descargaxbrlipp.ashx?t={GUID}` → raw XBRL.
- **ESEF:** `…/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif=<NIF>` → per-row `registro
  oficial` → individual/consolidado iXBRL (note: consolidated may use
  `webservices/verdocumento/ver?e=<opaque-token>`).

The next session must prove this path end-to-end for SAN, BBVA and IBE before R1 can flip to
`PASS`.

## Evidence

- `evidence/em_inffinanual` (`.html`/`.txt`), `evidence/busqueda-id25*`, `evidence/busqueda-id6-bbva.html`
- `evidence/xbrl-index.html`, `evidence/ipps-default.html`
- `evidence/datosentidad-bbva.html` / `.txt`, `evidence/sitemap_entidades.xml`
- `evidence/homepage.html` (source of GUID artefacts)
