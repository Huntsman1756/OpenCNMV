# R2 — SOURCE_ACCESS_MECHANISM

**Gate:** R2 — SOURCE_ACCESS_MECHANISM
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC 22:15)

## Objective

Characterise the real access mechanism per source family, and record session / postback /
cookie / redirect / anti-automation behaviour against the **current** portal (not hypotheses).

## Characterised mechanisms

| Family | Mechanism | Session | Postback | Cookies | Redirect | Evidence |
|---|---|---|---|---|---|---|
| Registry search (IFA `id=25`, interim `id=6`) | `FORM_POST` (ASP.NET WebForms) | viewstate/eventvalidation postback | **required** (`aspnetForm`, `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`) | `IdiomaCNMV_` (language) set on GET | `.aspx` → extensionless (URL rewrite) | `busqueda-id25*`, `busqueda-id6-bbva.html` |
| IPP XBRL tool (`/ipps`) | `OTHER` (ASP.NET AJAX / jQuery `$.ajax`, `ScriptResource.axd`) | yes | partial/AJAX | app-specific | — | `ipps-default.html` |
| Taxonomy ZIP | `DIRECT_URL` | no | no | none | none | `ipp_2019-01-01_run1.zip` |
| Raw artefact webservice | `DIRECT_URL` (GET) | no | no | **none** | none | `guid_doc_run1.pdf` |
| Entity registry page | `DIRECT_URL` (GET) + nested links | no | no | language cookie | `.aspx`→extensionless | `datosentidad-bbva.*` |

## Observed behaviour (recorded, not assumed)

- **Transport:** HTTP/1.1 over HTTPS; response `Content-Type: text/html; charset=utf-8` for
  pages; `Cache-Control: private`; `strict-transport-security: max-age=31536000`.
- **Cookie on first load:** server sets `IdiomaCNMV_` (a serialised .NET object encoding the
  language preference), path `/`, `secure`, 1-year expiry. **No `ASP.NET_SessionId`** was
  observed on the registry GET — the postback appears to rely on ViewState rather than classic
  session state.
- **URL rewriting:** requests to `*.aspx` are 302-redirected to the extensionless form
  (e.g. `…/busqueda.aspx?id=25` → `…/busqueda?id=25`). **Important:** a POST to the `.aspx`
  URL is followed as a GET, dropping the body — the form action is already extensionless
  (`./busqueda?id=25`).
- **Form controls (registry `id=25`):** `ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion`,
  `ctl00$ContentPrincipal$wFechas$fecha_desde`, `…$fecha_hasta`, `…$ult_dias`,
  `ctl00$ContentPrincipal$btnOk` (Buscar), `…$btnLimpiar` (Limpiar). The global search box is
  `ctl00$wBusqueda$txtBusqueda` (AddSearch site autocomplete).
- **Anti-automation:** none observed at the transport layer — ~25 requests over ~15 min all
  returned `200`; no captcha, no rate-limit, no 403, no cookie/Referer requirement for the
  webservice/static artefacts. `x-frame-options: sameorigin` and
  `content-security-policy: frame-ancestors 'self'` are present (no framing).

## Critical finding (affects source reliability)

A standard WebForms postback to `busqueda.aspx?id=25` / `id=6` (with `__VIEWSTATE` +
`__EVENTVALIDATION` + `txtDenominacion` + `btnOk=Buscar`) **re-renders the search page with zero
result rows**, verified with both HttpClient and curl. The response is byte-identical for
different denominations (`IBERDROLA`, `BANCO BILBAO`, `ult_dias=30`), which means the handler is
not executing the search under a bare postback. Hypotheses to test next (not assumed):
a) an ASP.NET session/`__EVENTTARGET` nuance, b) a JS/AJAX wrapper that transforms the submit,
c) results served by a different endpoint, d) the registry requires additional fields.

This is the single biggest source-access risk identified in R0–R4. It does **not** affect the
`DIRECT_URL` artefact webservice or static taxonomy download, which work statelessly.

## Evidence

- `evidence/busqueda-id25.html` (search form + viewstate), `evidence/busqueda-id25-*.html`
  (postback attempts, 0 rows), `evidence/busqueda-id6-bbva.html`
- `evidence/ipps-default.html`, `evidence/xbrl-index.html`
- `evidence/datosentidad-bbva.html`
