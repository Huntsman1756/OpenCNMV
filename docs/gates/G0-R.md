# G0-R.md — CNMV Source & Reproducibility Probe

G0-R is the mandatory gate set that must be executed and closed before any product, API, MCP,
interface or general-purpose infrastructure. It is a **source, evidence, parsing and
reproducibility probe**. Nothing more.

## Frozen corpus (corrected)

Issuers: **SAN** (Banco Santander), **BBVA**, **IBE** (Iberdrola).

```text
ESEF
  FY2024
  FY2025

IPP
  H1-2024
  H2-2024
  H1-2025
  H2-2025
  H1-2026
```

### Quarterly correction (Ley 5/2021, effective 2021-05-03)

Ley 5/2021 removed former art.120 of the LMV (Real Decreto Legislativo 4/2015), eliminating the
obligation to publish quarterly information. Therefore:

```text
Q1/Q3 <= 2021-05-02
    potentially IPP / required under former art.120 regime

Q1/Q3 >= 2021-05-03
    NOT_REQUIRED_AS_IPP

voluntary quarterly after that date
    potentially OIR / IP
    OUT_OF_SCOPE_G0
```

Q1/Q3 in 2024–2026 are **NOT part of the mandatory IPP corpus** and must not be labelled
`NOT_FOUND`. They are `NOT_REQUIRED_AS_IPP`.

### `availability_matrix` states

```text
AVAILABLE_XBRL
AVAILABLE_DOCUMENT_ONLY
NOT_REQUIRED
NOT_FOUND
SOURCE_ERROR
AMBIGUOUS
```

Critical rule: `NOT_FOUND != NOT_REQUIRED`.

When determinable, the matrix must carry:

```text
issuer, period, reporting_slot, expected_under_rule, discovered, submission_kind,
submission_scope, model_family, taxonomy_version, source_registration_no,
artifact_count, revision_count, status, evidence
```

### `expected_under_rule`

Must not depend only on Circular 3/2018. It must consider:

```text
rule + effective_from + effective_to + superior_law + filing_period
```

The Circular 3/2018 text still describes Q1/Q3, but the underlying obligation (former art.120)
was removed by a higher-rank norm. OpenCNMV must model this temporal suppression correctly.

## Source discovery (verified entrypoints)

Per-entity GET enumeration is the **preferred** path over reproducing the general WebForms search.

- **IPP:** `…/portal/consultas/ifi/listaifi?lang=es&nif=<NIF>` → stable `nreg`
  → `…/portal/aldia/detalleifialdia.aspx?nreg=<nreg>` → "Informe completo en formato"
  → `…/portal/consultas/wuc/descargaxbrlipp.ashx?t={GUID}` → raw XBRL.
- **ESEF:** `…/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif=<NIF>` → per-row
  `registro oficial` → individual/consolidado iXBRL. Note: consolidated iXBRL may serve via
  `webservices/verdocumento/ver?e=<opaque-token>` (variant to be tested).
- **Taxonomies (CNMV-owned):** `…/xbrl/xbrl` → `/IPP/taxonomia/<version>/ipp_<version>.zip`
  (Circulars 3/2018, 5/2015, 1/2008, 1/2005).
- **Raw artefact webservice:** `https://www.cnmv.es/webservices/verdocumento/ver?t=%7b<guid>%7d`.

Issuer identity:
- SAN → `BANCO SANTANDER, S.A.` → `nif=A39000013`.
- BBVA → `BANCO BILBAO VIZCAYA ARGENTARIA, S.A.` → `nif=A48265169`.
- IBE → `IBERDROLA, S.A.` → `nif=A-48010615`, `LEI=5QK37QC7NWOJ8D7WVQ45`.

## Execution order

Do not run the 18 gates in parallel.

First phase: **R0 → R4**, then checkpoint `CONTINUE / HOLD / STOP`. Only then **R5 → R17**.

## The gates

### R0 — LEGAL_REUSE_REVIEW
Review the CNMV legal notice, reuse conditions, attribution, limitations, and restrictions
relevant to bulk/republication; and robots/technical conditions. Produce documentary evidence.
Do not do a generalised crawl before closing R0.

### R1 — SOURCE_DISCOVERY_EXACT
Demonstrate how to locate **exactly** the target filings. Record `source_family`,
`discovery_entrypoint`, `input identifiers`, `output identifiers`, `evidence`. Do not assume a web
query equals an API.

### R2 — SOURCE_ACCESS_MECHANISM
Characterise the real mechanism per family: `API / DIRECT_URL / HTML_QUERY / FORM_POST /
SESSION_FORM / OTHER`. Record `requires_session`, `requires_postback`, `authentication`,
`cookies_required`, `referer_required`, `rate_limit_observed`, `anti_automation_behavior`.
Historical ASP.NET/WebForms details are hypotheses until verified on the current portal.

### R3 — DISCOVERY_STABILITY
Run discovery in ≥2 separated observations. Check identifier stability, link stability, ordering
changes, session dependence, behaviour under identical parameters.

### R4 — ARTIFACT_URL_STABILITY
Check whether final links work out-of-session, are reusable, contain a stable identifier, survive
between runs, and require no cookies/referer. Do not conflate discovery stability with artefact
stability. **Both corpus families (ESEF iXBRL and IPP XBRL) must be tested.** If the `?e=` token
changes per visit while yielding the same bytes, R4 remains FAIL (canonical identity must not
rest on the URL).

### R5 — ISSUER_IDENTITY_EXACT
Demonstrate unambiguous identity for SAN, BBVA, IBE. Separate `issuer`, `issuer_identifier`,
`security`. Do not make ISIN the primary issuer identity.

### R6 — SOURCE_FILING_KEY_STABLE
Find the best available source key. Prefer official published identifiers over hashes/synthetic
keys. Record any case where the identifier changes after substitution.

Observed source identity hierarchy (feeds R6):
```text
IPP  canonical source identity = nreg
ESEF canonical source identity = registro oficial
artifact locator              = webservices/verdocumento/ver?e=<token>   (stable)
ephemeral transport locator   = descargaxbrlipp.ashx?t={GUID}            (never identity)
```
Use `nreg` / `registro oficial` as `source_registration_no`; use the stable `?e=` token as the
per-artefact locator; never use the ephemeral `?t={GUID}` as identity.

### R7 — RAW_ARTIFACT_RETRIEVAL
Download original artefacts. Never re-serialise before preserving the raw. Record `source_url`,
`retrieved_at`, HTTP metadata, `media_type`, `byte_size`.

### R8 — RAW_SHA256_STABLE
Compute SHA-256 of each raw artefact. A second download must produce the same hash or demonstrate
the source changed. Never silently overwrite prior bytes.

### R9 — TAXONOMY_DISCOVERY
For each XBRL artefact determine `taxonomy`, `taxonomy_version`, `namespace`, required
packages/resources. Must handle historical IPP taxonomy heterogeneity.

### R10 — TAXONOMY_PINNING
Freeze dependencies for reconstruction. Produce `taxonomy_manifest.json` with `package`,
`source_url`, `retrieved_at`, `sha256`, `taxonomy_version`, `filing_family`, `required_by`. Pin
the exact Arelle version and relevant configuration.

### R11 — ESEF_ARELLE_PARSE
Demonstrate ESEF parsing with Arelle. No alternative parser unless documented Arelle failure.
Verify preservation of concepts, contexts, units, dimensions, decimals, facts.

### R12 — IPP_ARELLE_PARSE
Demonstrate IPP parsing with Arelle. Deliberately cover:
- credit-entity model;
- general model;
- H1;
- H2;
- taxonomy/model heterogeneity **actually observed** within the frozen corpus.

Record taxonomy incompatibilities, do not hide them. (Q1/Q3 post-2021-05-03 are `NOT_REQUIRED_AS_IPP`
and are **not** a corpus requirement for R12. Parsing pre-Circular 3/2018 taxonomies, if desired,
is an explicit additional **fixture**, not a mandatory R12 criterion.)

### R13 — SOURCE_REVISION_DETECTION
Test `13A REVISION_EXISTS`, `13B REVISION_TARGET_EXACT`, `13C REVISION_SEMANTICS_EXTRACTED`.
Include cases where the submission type changes if found. Do not infer perfect amendment chains
without evidence.

### R14 — ONLINE_CAPTURE_DETERMINISTIC
With the same observation/source state, the pipeline must generate semantically identical output.
Exclude from the logical hash: execution timestamps, temporary paths, non-deterministic logs.

### R15 — OFFLINE_REBUILD_DETERMINISTIC (critical)
Run with network denied. Inputs allowed: raw artefacts, pinned taxonomy packages, exact Arelle
version, configuration, canonicalizer code, manifests. Must produce exactly the same semantic
artefacts: canonical metadata, native fact dataset, artefact manifest, derived deterministic
outputs. If it needs Internet → FAIL.

### R16 — ESEF_EXTERNAL_ORACLE_RECONCILIATION
Compare CNMV ESEF filings against `filings.xbrl.org/es-cnmv`. Detect omissions, misalignments,
identity/period issues, amended reports. Do not substitute the oracle for CNMV. Explain or open
every divergence as a finding.

### R17 — H2_VS_ESEF_PERIOD_RECONCILIATION
Demonstrate: (1) H2 and FY/ESEF are distinct filings; (2) they can share issuer + fiscal year +
period_end; (3) H2 `submission_scope` preserved; (4) all native XBRL contexts preserved;
(5) `CURRENT_HALF != YTD` when the source distinguishes them; (6) dimensions not collapsed;
(7) an H2 revision caused by the IFA can be represented; (8) fact comparison ≠ semantic
equivalence; (9) the second-semester vs annual-cumulative duality is preserved within the H2.

## Evidence required per gate

Each gate must produce a directory `g0-r/Rxx-*` containing at minimum:

```text
README.md
evidence/
manifest.json
```

`manifest.json` fields: `gate`, `status`, `executed_at`, `code_commit`, `inputs`, `outputs`,
`sha256`, `findings`, `limitations`. Status values only: `PASS`, `FAIL`, `NOT_APPLICABLE`.

## Definition of Done of G0-R

Closed only when there are explicit results for **R0–R17**. The final verdict must be:

```text
GO | CONDITIONAL_GO | NO_GO
```

accompanied by: `passed_gates`, `failed_gates`, `not_applicable_gates`, `known_source_risks`,
`known_model_risks`, `legal_constraints`, `reproducibility_result`, `recommended_next_step`.

A final `GO` would authorise **G1 design**. It does **not** automatically authorise building a full
platform. G1 is **not** touched until R17 is closed.

## Checkpoint logic (after R0–R4)

After R0–R4 produce a checkpoint with states **`CONTINUE` / `HOLD` / `STOP`**:

- `CONTINUE` = the four foundations hold (reuse legally viable; discovery reproducible; access
  mechanism sufficiently stable; artefacts recoverable reliably) and you may proceed to **R5**.
- `HOLD` = one or more foundations need targeted resolution before continuing.
- `STOP` = a structural failure; do not continue automatically.

A `CONTINUE` does **not** authorise designing G1. G1 is only touched once the final G0-R verdict
(after R17) is `GO`. A `CONTINUE` authorises continuing the G0-R gates (R5 → R17).
