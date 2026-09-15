# G0-R — CNMV Source & Reproducibility Probe (Session 1: R0–R4)

**Scope of this session:** R0–R4 only. No R5+, no product, no API, no UI.

**Executed:** 2026-09-14 (UTC 22:15)
**Workspace:** `F:\_Proyectos\OpenCNMV`
**Probe tooling:** `g0-r/_probe-logs/*.ps1` (HttpClient + curl + HTML-to-text helpers)

---

## Gate summary

| Gate | Status |
|---|---|
| R0 — LEGAL_REUSE_REVIEW | **PASS** |
| R1 — SOURCE_DISCOVERY_EXACT | **PASS** (exact corpus enumeration → artefact proven via `listaifi`/`ListadoIFA`) |
| R2 — SOURCE_ACCESS_MECHANISM | **PASS** (with a critical finding) |
| R3 — DISCOVERY_STABILITY | **PASS** |
| R4 — ARTIFACT_URL_STABILITY | **PASS** (both corpus families proven byte-stable out-of-session) |

---

## Key verified facts

### Source surfaces (CNMV official)
- IFA / annual financial reports (incl. ESEF): `…/portal/consultas/em_inffinanual.aspx?id=EE`
  → `…/portal/consultas/busqueda.aspx?id=25`.
- Interim / IPP: `…/portal/consultas/busqueda.aspx?id=6`.
- IPP XBRL viewer & download: `…/ipps/default.aspx` (separate ASP.NET AJAX app).
- IPP taxonomies (CNMV-owned, versioned, tied to Circulars 3/2018, 5/2015, 1/2008, 1/2005):
  `…/IPP/taxonomia/<version>/ipp_<version>.zip`.
- Raw artefact webservice: `https://www.cnmv.es/webservices/verdocumento/ver?t=%7b<guid>%7d`.
- Per-entity aggregated registry: `…/portal/consultas/datosentidad.aspx?nif=<NIF>`.

### Issuer identity
- SAN → `BANCO SANTANDER, S.A.`, key `nif=A39000013`.
- BBVA → `BANCO BILBAO VIZCAYA ARGENTARIA, S.A.`, key `nif=A48265169`.
- IBE → `IBERDROLA, S.A.`, **NIF unresolved** (open finding for R5).

### Access mechanism
- Registry search = ASP.NET WebForms `FORM_POST` (`__VIEWSTATE`/`__EVENTVALIDATION`).
- Only cookie set is `IdiomaCNMV_` (language); no `ASP.NET_SessionId` observed.
- `.aspx` URLs 302-redirect to extensionless; a POST to `.aspx` is followed as GET (body lost).
- Artefact webservice + static taxonomy = stateless `DIRECT_URL`, no cookies, no redirect.
- No anti-automation (captcha/rate-limit/403) observed across ~25 requests.

### Stability (R3)
- XBRL page byte-identical across two observations; discovery URIs identical (27/27, 65/65,
  zero diffs); `webservices/verdocumento/ver?t=%7b<guid>%7d` pattern stable.

### Artifact URL stability (R4)
- GUID artefact: two fresh downloads, identical SHA-256 `E78E3F2F…`, no cookies/session.
- Taxonomy ZIP: two downloads, identical SHA-256 `87C44522…`, direct static file.

---

## Checkpoint decision

### `GO`

**Rationale (R0–R4 resolution session).** All four checkpoint foundations are met:

1. **Reuse legally viable** — R0 PASS (private use + faithful reproduction + calculation use +
   no-framing conditions). No written agreement required for a source probe.
2. **Discovery reproducible** — R3 PASS, reinforced this session: `ListadoIFA` is byte-identical
   across observations and the 18 ESEF `?e=` tokens are identical between visits.
3. **Access mechanism stable** — R2 PASS; the per-entity GET path (`listaifi`/`ListadoIFA`) is
   deterministic and requires no WebForms postback, no session, no cookies.
4. **Artefacts recoverable reliably** — R4 PASS: IPP raw XBRL and ESEF iXBRL are byte-stable
   out-of-session for SAN, BBVA and IBE (identical SHA-256 across repeated downloads).

**Key finding of the resolution session:** the IPP `?t={GUID}` intermediate is **ephemeral**
(changes per visit) but always redirects to the same stable `?e=` token and the same bytes.
Therefore the canonical identity must use the stable `nreg` (IPP) / `registro oficial` (ESEF) as
`source_registration_no`, never `?t={GUID}`. This is a model-level rule to carry into R5+.

A `GO` authorises **G1 design**, not a full platform. R5 → R17 still remain to be executed within
G0-R.

---

## Known source risks

- **Registry-search postback not yielding rows** (R2 critical finding) — **resolved** by using the
  per-entity GET path (`listaifi?nif=` / `ListadoIFA?nif=`); the general WebForms search is
  bypassed and should not be invested in.
- **IPP `?t={GUID}` is ephemeral** — changes per visit; always redirects to a stable `?e=` token
  and the same bytes. Canonical identity must use `nreg` / `registro oficial`, never `?t={GUID}`.
- **Long-horizon token/URL drift** — to be monitored in R8 (RAW_SHA256_STABLE).
- **Issuer-authored filings may carry third-party copyright** not covered by CNMV's reuse terms
  (R0 limitation).
- **Entity sitemap is only a partial sample**, not a comprehensive issuer index.

## Known model risks

- `submission_kind` / `submission_scope` cannot be inferred from the discovery page alone; they
  must come from the artefact + applicable rules (deferred to the R13+ model work).
- `expected_under_rule` must depend on `rule + effective_from + effective_to + superior_law +
  filing_period`, not just on Circular 3/2018 (Q1/Q3 post-2021-05-03 are not required).
- The artefact identity mapping is: `source_registration_no` = `nreg` (IPP) / `registro oficial`
  (ESEF); the per-artefact identifier is the stable `?e=` token.

## Evidence index

See each gate's `README.md` and `manifest.json`:

| Gate | README | Manifest |
|---|---|---|
| R0 | `g0-r/R00-legal/README.md` | `g0-r/R00-legal/manifest.json` |
| R1 | `g0-r/R01-discovery/README.md` | `g0-r/R01-discovery/manifest.json` |
| R2 | `g0-r/R02-access/README.md` | `g0-r/R02-access/manifest.json` |
| R3 | `g0-r/R03-stability/README.md` | `g0-r/R03-stability/manifest.json` |
| R4 | `g0-r/R04-artifact-url-stability/README.md` | `g0-r/R04-artifact-url-stability/manifest.json` |

Probe scripts (reusable): `g0-r/_probe-logs/probe.ps1`, `cnmv-postback.ps1`,
`curl-postback.ps1`, `html-to-text.ps1`, `extract-query.ps1`.

---

## Recommendation

**Checkpoint is `GO` — proceed to R5 (within G0-R).** The R0–R4 probe is closed. Next work should
begin the R5→R17 gates (issuer identity exact, source filing key, raw artefact retrieval,
SHA-256 stability, taxonomy discovery/pinning, Arelle parsing, revision detection, determinism).
Continue to follow `AGENTS.md` and `docs/gates/G0-R.md`; do **not** build product, UI, API, or MCP.
Update `docs/STATUS.md` at the end of each session.
