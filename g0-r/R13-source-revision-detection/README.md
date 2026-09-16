# R13 — SOURCE_REVISION_DETECTION

**Gate:** R13 — SOURCE_REVISION_DETECTION
**Status:** `PASS`
**Executed:** 2026-09-16 (UTC)

## Objective

Per `docs/gates/G0-R.md`: test `13A REVISION_EXISTS`, `13B REVISION_TARGET_EXACT`,
`13C REVISION_SEMANTICS_EXTRACTED`; include cases where the submission type changes if
found; do not infer perfect amendment chains without evidence. Also resolves the caveat
R6 deferred here: whether the official registration key survives a real substitution.

## Method

`r13_detect.py` re-fetches the three `ListadoIFA` pages (recorded with sha256 +
retrieved_at + HTTP metadata in `evidence/fetch_manifest.json`), parses the
`Ampliación información` column (col 8) of every row, follows each `infadicionifa`
link `(nreg, nregaud)` for the six corpus rows (SAN/BBVA/IBE × FY2024/FY2025) plus the
IBE-FY2022 falsification fixture (registro `19646`), classifies each published event,
and verifies the exact target binding. For 13C it fetches the two IBE-FY2022
certificate PDFs and the IBE H1-2009 IPP PDF and extracts the in-document correction
semantics deterministically (regex over `pypdf` text — no LLM, no heuristics beyond
fixed patterns).

## 13A REVISION_EXISTS — PROVEN

- **Every corpus ESEF row carries `Sí`** in `Ampliación información` (6/6). Each
  `infadicionifa` page resolves to exactly one event, classified `CERTIFICATE`
  ("Certificado del secretario del consejo sobre la formulación y firma del informe
  financiero anual"). `Sí` therefore does **not** imply a revision: the column bundles
  complementary certificates. No in-corpus substitution exists.
- **Fixture IBE FY2022 (registro 19646, outside the frozen corpus):** two events —
  `CERTIFICATE` (formulación y firma, 24/02/2023) and `SUBSTITUTION`
  ("…sobre la **sustitución** del informe financiero anual", 28/02/2023), each with a
  `verdocumento/ver?e=` document (PDFs captured + hashed).
- **IPP side:** the `listaifi` listing exposes only `Fecha de publicación` / `Tipo de
  información` — **no revision/ampliación mechanism exists at listing level**, and
  `detalleifialdia` shows no substitution markers. IPP revisions surface only
  **inside the document** (see 13C).
- **R6 correction (finding):** R6 §falsification-3 states the `Ampliación información`
  column "is empty for every corpus row". The R1 snapshot itself contains `Sí` on all
  six corpus rows — that claim was an **observation error**, now corrected. Row-level
  comparison of the R1 snapshot vs the R13 re-fetch shows an **identical ampliación
  set and no added registros** (only page byte drift). R6's conclusion is unaffected:
  `registro oficial`/`nreg` remain the logical keys; what changes is that corpus rows
  *do* have attached complementary documents (all `CERTIFICATE`, none revisions).
- No submission-type change was found; the IBE-FY2022 substitution replaced the same
  filing's content under the same registro (below).

## 13B REVISION_TARGET_EXACT — PROVEN (ESEF)

- The `infadicionifa` URL itself encodes the binding:
  `nreg` = registration of the complementary-info submission;
  `nregaud` = **Nº Registro Oficial of the target IFA**.
- For all 7 pages fetched: `nregaud` param ≡ `registro` shown in the page header ≡
  the listing row's registro oficial (`target_exact_checks`, all `true`). The target
  is **given by the source** — no issuer+period inference is used or needed.
- **ESEF `registro oficial` persistence across substitution = PROVEN:** the page
  addressed by `nregaud=19646` contains the substitution event; the same registro
  holds both the formulation certificate and the substitution certificate.
  Corroboration of the R6 legend semantics, now observed: the row's
  `fecha_publicacion` is `28/02/2023`, equal to the substitution certificate's date —
  "date of the last substitution" — while the registro did not change.
- **IPP `nreg` persistence across substitution = NOT_YET_PROVEN.** No listing-level
  revision mechanism exists to observe; this asymmetry is recorded honestly rather
  than assumed.

## 13C REVISION_SEMANTICS_EXTRACTED — PROVEN

Fixture: `ibe-h1-2009-ipp.pdf` (IBE 1er informe financiero semestral 2009,
pre-XBRL PDF, `verdocumento/ver?e=…`, sha256 in fetch manifest). Deterministic
`pypdf` extraction of section **"II. INFORMACIÓN COMPLEMENTARIA A LA INFORMACIÓN
PERIÓDICA PREVIAMENTE PUBLICADA"** yields (`h1_2009_semantics` in
`r13_results.json`):

- **nature:** in-document correction of previously published periodic information
  (`Explicación de las principales modificaciones…`).
- **reason:** June-2009 Board decision to contribute the gas/electricity retail
  business to Iberdrola Generación → discontinued operations → mandatory comparative
  restatement (PGC), plus reclassification of current tax assets/liabilities in the
  comparative 31/12/2008 balance.
- **adjustment_amounts** (miles de euros), `Corregida / Previamente presentada /
  Diferencia`, consolidated and individual:
  - Activos por impuestos corrientes: 484.641 / 1.017.757 / −533.116 (cons);
    446.671 / 0 / +446.671 (ind)
  - Pasivos por impuestos corrientes: 477.352 / 1.398.121 / −920.769 (cons);
    4.829 / 0 / +4.829 (ind)
- **affected_periods:** comparative balance at 31/12/2008; H1-2008 result
  reclassified to "operaciones interrumpidas" for comparability.
- **annual_accounts_trigger / referenced_annual_filing:** not present in this
  fixture — recorded as absent rather than invented.
- Source evidence: raw PDF + sha256 + extracted text (`ibe-h1-2009-ipp.txt`) +
  excerpt hash. The same semantic channel (certificates with `ver?e=` documents,
  dates, motives) exists on the ESEF side via `infadicionifa`.

## Findings

1. `Ampliación información = Sí` is present on **all six** corpus ESEF rows and means
   "complementary documents exist", dominated by `CERTIFICATE` events — it is a
   revision-*detection surface*, not a revision marker.
2. ESEF revision events bind to their target via `nregaud` = registro oficial —
   exact, source-provided, no inference. `filing` = registro; each event (and the
   `?e=` artefact version) = `filing_version` material.
3. ESEF registro survives a real substitution (IBE FY2022, registro 19646);
   `fecha_publicacion` tracks the last substitution. This closes the R6 caveat
   **for ESEF only**.
4. IPP exposes no equivalent mechanism: `listaifi` has two columns and no revision
   surface. `nreg` persistence across substitution remains `NOT_YET_PROVEN`; IPP
   revisions are in-document (13C fixture).
5. R6 §3 "column empty for every corpus row" was an observation error — corrected by
   row-level re-parse of the unchanged R1 snapshot (no semantic drift since R1).
6. Arelle/`ver?e=` tokens on `infadicionifa` pages are per-document artefact
   locators, same class as the filing `?e=` tokens (R4/R6).

## Limitations

- The listing serves only the **current** version of a filing; no superseded-version
  locator was found, so byte-level before/after diff of a substituted ESEF package is
  not demonstrable from the source listing.
- Classification is deterministic keyword mapping over official `motivo` strings;
  an `OTHER` bucket exists and would surface unclassified events (none occurred).
- IPP revision *detection* cannot rely on a listing column — only on document
  content (13C) or new-`nreg` observation; the latter was not observed.
- 13C fixture is a pre-XBRL IPP (PDF); in the XBRL-era corpus the equivalent channel
  is taxonomy concepts inside the instance, which R12 preserves verbatim.

## Evidence

- `evidence/fetch_manifest.json` — url, retrieved_at, status, media_type, bytes, sha256
- `evidence/ListadoIFA-{SAN,BBVA,IBE}-r13.html` — current listings (drift-checked vs R1)
- `evidence/infadicionifa-{19646,20448,20509,20515,20854,20875,20934}-r13.html`
- `evidence/ibe-fy2022-cert{1,2}.pdf` — formulation + substitution certificates
- `evidence/ibe-h1-2009-ipp.pdf` / `.txt` — 13C fixture raw + extracted text
- `evidence/r13_results.json` — events, classes, target bindings, semantics, drift
- `g0-r/R01-discovery/evidence/ListadoIFA-*.html` — R1 snapshots (comparison base)
