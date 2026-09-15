# ADR-0001 — Use per-entity GET enumeration over the general WebForms search

- **Date:** 2026-09-14
- **Status:** Accepted
- **Related gates:** R1, R2, R4

## Context

The general registry search on the CNMV portal (`…/portal/consultas/busqueda.aspx?id=25` for IFA
and `…/busqueda.aspx?id=6` for interim/IPP) is an ASP.NET WebForms postback. In session 1, a bare
automated postback (with correct `__VIEWSTATE` / `__EVENTVALIDATION` and a denomination) **re-renders
the search page with 0 result rows**, verified with two independent HTTP clients (HttpClient and
curl). Reproducing the exact browser postback/session/`__EVENTTARGET`/AJAX semantics is costly and
fragile.

## Decision

Do **not** invest in reproducing the general WebForms search postback. Instead, use the **per-entity
GET enumeration** surfaces, which expose direct, GET-addressable lists keyed by the issuer NIF:

- **IPP:** `…/portal/consultas/ifi/listaifi?lang=es&nif=<NIF>` → stable `nreg`
  → `…/portal/aldia/detalleifialdia.aspx?nreg=<nreg>` → "Informe completo en formato"
  → `…/portal/consultas/wuc/descargaxbrlipp.ashx?t={GUID}` → raw XBRL.
- **ESEF:** `…/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif=<NIF>` → per-row
  `registro oficial` → individual/consolidado iXBRL (note: consolidated may serve via
  `webservices/verdocumento/ver?e=<opaque-token>`).

Chain: `NIF → listaifi/ListadoIFA → nreg/registro oficial → detail → XBRL GUID/token → raw XBRL`.

## Consequences

- Enables deterministic per-issuer, per-period enumeration without a browser session.
- Uses identifiers we already want in the model (`source_registration_no` = `nreg` / `registro
  oficial`, and the artefact GUID).
- Must still prove end-to-end for SAN, BBVA and IBE, and verify the `?e=` (ESEF) and `?t=` (IPP)
  variants are stable/out-of-session before R1/R4 can pass.
- If the `?e=` token changes per visit while returning the same bytes, the canonical identity must
  not rely on the URL; the downloader must regenerate it via discovery.

## Rejected alternatives

- Reproducing the general `busqueda.aspx?id=X` WebForms postback (costly, fragile, returned 0 rows
  in automated tests).
- Relying on `filings.xbrl.org/es-cnmv` (oracle) as the enumeration source (it is an oracle only).
