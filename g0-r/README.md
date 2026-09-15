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
| R1 — SOURCE_DISCOVERY_EXACT | **FAIL** (exact corpus enumeration not yet proven) |
| R2 — SOURCE_ACCESS_MECHANISM | **PASS** (with a critical finding) |
| R3 — DISCOVERY_STABILITY | **PASS** |
| R4 — ARTIFACT_URL_STABILITY | **FAIL** (target artefact families not both proven) |

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

### `HOLD`

**Rationale.** Three of the four checkpoint foundations are clearly met:

1. **Reuse legally viable** — R0 PASS (private use + faithful reproduction + calculation use +
   no-framing conditions). No written agreement required for a source probe.
2. **Discovery reproducible** — R3 PASS (entrypoints and identifiers stable across two
   observations).
3. **Artefacts recoverable reliably** — R4 PASS (artefact webservice and static taxonomy are
   deterministic, stateless, and SHA-256-stable).

The blocking item is the **discovery→artefact bridge for the actual corpus filings**:

> A bare automated WebForms postback to `busqueda.aspx?id=25` / `id=6` (with correct
> `__VIEWSTATE`/`__EVENTVALIDATION` and a denomination like `IBERDROLA` / `BANCO BILBAO`)
> **re-renders the search page with 0 result rows** — verified with two independent HTTP clients
> (HttpClient and curl). The response is byte-identical across different denominations, meaning
> the search handler does not execute under a bare postback.

Consequences:
- I can retrieve a **known** artefact (given a GUID) and download a **known** taxonomy, but I
  cannot yet **enumerate** the IFA/ESEF and IPP filings for SAN/BBVA/IBE to obtain their GUIDs.
- Therefore the specific corpus filings (SAN/BBVA/IBE, FY2024–FY2025 ESEF, IPP quarters/H1/H2)
  have **not yet been retrieved end-to-end** in this session.

**What must be demonstrated to flip to `GO`:**
1. Prove the per-entity GET enumeration path end-to-end for SAN, BBVA and IBE:
   - **IPP:** `…/portal/consultas/ifi/listaifi?lang=es&nif=<NIF>` → stable `nreg`
     → `…/portal/aldia/detalleifialdia.aspx?nreg=<nreg>` → "Informe completo en formato"
     → `…/portal/consultas/wuc/descargaxbrlipp.ashx?t={GUID}` → raw XBRL.
   - **ESEF:** `…/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif=<NIF>` → per-row
     `registro oficial` → individual/consolidado iXBRL (note: consolidated may use
     `webservices/verdocumento/ver?e=<opaque-token>`).
2. Retrieve one real **ESEF iXBRL** and one **IPP** filing end-to-end for the corpus, hash them
   out-of-session, and confirm byte-stability (R4/R8 groundwork). If the `?e=` token changes per
   visit while returning the same bytes, R4 stays `FAIL` and the canonical identity must not rely
   on the URL.
3. Accept the corrected corpus (Q1/Q3 post-2021-05-03 are `NOT_REQUIRED_AS_IPP`; see
   `docs/gates/G0-R.md`).

These are targeted and likely resolvable; they are not structural showstoppers (the source is
clearly usable at the artefact level), which is why the verdict is `HOLD`, not `STOP`.

---

## Known source risks

- **Registry-search postback not yielding rows** (R2 critical finding) — can likely be bypassed by
  the per-entity GET path (`listaifi?nif=` / `ListadoIFA?nif=`), but that path is still unproven.
- **ESEF `?e=<token>` stability** — the consolidated iXBRL may use an opaque token rather than the
  `?t={GUID}`; must be tested before R4 can pass.
- **Issuer-authored filings may carry third-party copyright** not covered by CNMV's reuse terms
  (R0 limitation).
- **Entity sitemap is only a partial sample**, not a comprehensive issuer index.

## Known model risks

- None blocking for R0–R4, but note: the artefact webservice key is a GUID (opaque), which may
  not expose issuer/period/version directly — the mapping must be derived from the discovery
  results once enumeration is solved.
- `submission_kind` / `submission_scope` cannot be inferred from the discovery page alone; they
  must come from the artefact + applicable rules (deferred to the R13+ model work).
- `expected_under_rule` must depend on `rule + effective_from + effective_to + superior_law +
  filing_period`, not just on Circular 3/2018 (Q1/Q3 post-2021-05-03 are not required).

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

**Hold and resolve R1/R4 only, via the per-entity GET path — do not invest in the WebForms POST.**
Next session should: (a) freeze IBE identity (`NIF A-48010615`, `LEI 5QK37QC7NWOJ8D7WVQ45`);
(b) probe `listaifi?nif=` and `ListadoIFA?nif=` for SAN, BBVA, IBE; (c) run the IPP chain
`NIF → nreg → XBRL GUID` and the ESEF chain `NIF → registro oficial → consolidated iXBRL`
end-to-end, downloading each twice out-of-session and comparing SHA-256; (d) inspect the `?e=`
token behaviour; (e) repeat discovery and compare `nreg` / GUID / `e`-token / final bytes; (f)
re-evaluate R1 and R4. Do **not** build product, UI, API, or MCP until enumeration + exact
per-filing retrieval is demonstrated. Also update `docs/STATUS.md` at the end of each session.
