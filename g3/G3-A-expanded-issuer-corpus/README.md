# G3-A — EXPANDED_ISSUER_CORPUS (preregistration)

Status: **PREREGISTERED** (sample frozen separately; see "Freeze protocol").

This document is the frozen contract for the gate. It is written **before any
filing capture** outside the G2 frozen corpus (SAN/BBVA/IBE). The issuer
sample below is produced by the preregistered freeze protocol and committed
as `sample.json` before the first filing request of this gate.

## Question

> Can the production capture/bootstrap/update/query pipeline process a
> preregistered heterogeneous issuer sample outside SAN/BBVA/IBE without
> issuer-specific code, silent coercion, or Canonical Model V1 violations?

## Why a stratified sample

Capturing "all CNMV issuers" would conflate sampling noise with model
failures and make triage unbounded. A fixed, documented, stratified sample
falsifies the generalisation claim at bounded cost: if the model only
survives SAN/BBVA/IBE, the sample must contain the cases most likely to
break it — different sectors, different IPP model families, different
filing behaviours, different extension taxonomies, different sizes.

## Universe and enumeration surfaces (official CNMV only)

| surface | endpoint | yields |
|---|---|---|
| IFA issuer universe | `POST /portal/consultas/busqueda?id=25&lang=es` with empty `txtDenominacion` and a wide filing-date window | issuer picker options: `(nif, legal denomination)` for every entity with ≥1 IFA filing in the window |
| issuer identity/sector | `GET /portal/consultas/ee/datosgenerales.aspx?nif={nif}&lang=es` | official registry row: NIF, LEI, denominación abreviada, `Sector` (CNMV 2-level taxonomy), capital social |
| IPP filing list per issuer | `GET /portal/consultas/ifi/listaifi?lang=es&nif={nif}` | IPP rows: period, semester, `detalleifialdia?nreg=` links |
| IFA filing list per issuer | `GET /portal/consultas/IFA/ListadoIFA?id=0&lang=es&nif={nif}` | IFA rows: registro oficial, period, doc-type cells, `detalleifialdia`/`infadicionifa` links |
| recent IPP universe | `GET /portal/consultas/ifi/listaifi?lang=es` (no nif) | latest IPP filings across issuers (supplementary evidence) |

No third-party source is used for selection or classification. Sector and
size strata are computed **only** from the official registry fields
(`Sector`, `Capital social`) — never from issuer-name inference.

## Freeze protocol (runs before filing capture)

`g3a_freeze.py` performs, in one `PoliteSession` (declared UA, sequential,
min delay 2.5 s), and preserves every response byte-for-byte under
`_out/freeze/` (write-once, content-addressed) with sha256:

1. **Universe enumeration** — 1 POST `busqueda?id=25`, empty denomination,
   window `desde=2024-01-01` → `hasta=<freeze date>`; parse picker options
   → `universe.json` (nif, denomination). Expected order of magnitude:
   ~400 issuers.
2. **Unfiltered IPP listing** — 1 GET `listaifi` (no nif). Supplementary.
3. **Identity enrichment** — 1 GET `datosgenerales?nif=` per universe nif
   (bound: ≤ 600 requests). Missing/empty registry row → issuer marked
   `IDENTITY_UNRESOLVED` and excluded from the pool (recorded, not patched).
4. **Stratified selection** — deterministic rules below → `sample.json`.
5. **Expected-inventory listing** — for each sampled issuer, 1 GET
   `listaifi?nif=` + up to 3 GET `ListadoIFA?id=0&nif=` pages →
   `expected_inventory.json`: the filings the capture leg *must* find for
   the declared scope, plus event/infadicion candidates used to designate
   the substitutions stratum.

Total freeze request bound: **≤ 700 requests**. Freeze output is committed
(`sample.json`, `expected_inventory.json`, `universe.json`,
`freeze_manifest.json`) **before** the first filing-capture request of
this gate; the manifest records freeze-vs-capture timestamps so ordering
is auditable.

## Sample

Size: **40 issuers** (within the agreed 30–50 band). SAN/BBVA/IBE are
excluded by construction — they are covered by the frozen corpus and the
G2 regression battery.

Sector strata (selection over the official `Sector` field, tie-broken by
nif ascending):

| stratum | CNMV sector filter | n | rule |
|---|---|---|---|
| credit institutions | `FINANCIACIÓN Y SEGUROS/BANCOS` + cajas/cooperativas de crédito subgroups | 8 | top by capital |
| insurance entities | `FINANCIACIÓN Y SEGUROS/SEGUROS` | 2 | top by capital |
| utilities | `ENERGÍA Y AGUA/*` | 5 | top by capital |
| real estate / SOCIMI | `CONSTRUCCIÓN*/INMOBILIARIA*` + SOCIMI subgroups | 6 | top by capital |
| large industrials | any other sector | 7 | top by capital |
| small/mid caps | any sector | 8 | bottom by capital |
| securitisation funds | `FINANCIACIÓN Y SEGUROS/FONDOS DE TITULIZACIÓN` | 2 | nif ascending |
| residual sectors | sectors not yet represented | 4 | nif ascending |

**Amendment 1 (2026-09-18, before any filing capture):** the
`insurance-entities` stratum was added after the first freeze run showed
the credit pool is bounded — the universe contains only 8 `BANCOS`
issuers, two of which are SAN/BBVA (excluded by construction), leaving 6.
Insurers are financial entities filing IFA under a *different IPP model
family* (insurance vs credit vs general), which strengthens exactly the
"different IPP model families" stratum this gate wants to falsify. The
credit-institutions deficit (6/8) is recorded honestly as a universe
bound, not padded.

Behaviour strata are **designated at freeze** where evidence allows and
**verified on captured evidence**; issuers may satisfy several strata:

| stratum | designation | minimum | verified by |
|---|---|---|---|
| ES+EN ESEF variants | large issuers (banks + industrials + utilities) | ≥ 5 issuers | observation variant stats |
| ES-only | small/mid + FT issuers | ≥ 5 issuers | observation variant stats |
| substitutions / complementary events | issuers whose freeze ListadoIFA rows show ≥2 filings for one period or infadicion links | ≥ 1 issuer | event rows in observation |
| distinct extension taxonomies | organic | ≥ 3 distinct extension base URIs | artifact/taxonomy inventory |
| IPP model families | banks → HYBRID/credit model; general → FULL; FTs → fund model | ≥ 2 families | taxonomy/modelo per IPP filing |
| historical depth | deterministic subsample of 10 (2 per main stratum, nif-ascending) | 10 | — |

If a behaviour stratum's minimum is not met by reality, the corresponding
check **fails honestly** and the manifest records the actual coverage —
the sample is never padded post-hoc.

## Per-issuer capture scope (uniform rule)

Applied mechanically from the freeze inventory — identical rule for every
issuer, no per-issuer tuning:

- **ESEF**: the most recent listed IFA period. Historical subsample: the
  two most recent listed IFA periods.
- **IPP**: the two most recent listed IPP periods. Historical subsample:
  the four most recent listed IPP periods.
- All `infadicionifa`/event documents reachable from in-scope registry
  rows are captured, as in G2-F.
- Registry rows outside the declared scope are recorded as out-of-scope
  warnings, never silently captured.

If a sampled issuer's listing shows no IFA period (e.g. fund without ESEF
obligation) or no IPP period, that family is recorded
`SCOPE_EMPTY` for the issuer — an honest finding, not a selection fix.

## Required production changes (contract)

1. `opencnmv observe` accepts `--issuer-registry FILE` — a JSON registry
   (`ISSUER_REGISTRY_V1`) carrying `{nif → {key, denomination, lei,
   sector, scope}}`. `key` is generated at freeze as a deterministic
   ASCII slug of the official *denominación abreviada*. Without the flag,
   the built-in frozen registry keeps G2 semantics unchanged.
2. Period scope comes **from the registry artifact**, not module
   constants: `ESEF_PERIODS`/`IPP_SLOTS` remain the frozen defaults;
   registry `scope` overrides them. Filing/variant labels are derived
   mechanically from evidence (`dd/mm/yyyy` → `FY<year>`;
   `semester+year` → `H<n>-<year>`), never from lookup tables.
3. `resolve_scope` stays fail-closed: issuers outside the active
   registry are rejected.
4. LEI for expanded issuers is sourced from the official `datosgenerales`
   registry row (preserved freeze evidence); the captured ESEF entity
   identifier may cross-check it — a mismatch is
   `IDENTITY_UNRESOLVED`, never silently resolved.
5. No issuer-specific code paths: the gate scans the production diff for
   issuer literals/conditionals.

## Acceptance matrix

| check | requirement |
|---|---|
| G3A-1 | zero issuer-specific conditionals: no sample NIF/key literals and no `if issuer…`-style branching in production modules (scan) |
| G3A-2 | `observe --issuer-registry sample.json` drives discovery for the whole sample; G2 default registry behaviour unchanged (existing tests still pass) |
| G3A-3 | freeze evidence preserved + hashed; `sample.json` committed before first filing request (manifest timestamps) |
| G3A-4 | stratum coverage equals the preregistered quotas (or honestly recorded deficits with cause) |
| G3A-5 | capture of the full sample completes; every filing either represented or classified `UNRESOLVED` with a cause from the taxonomy below |
| G3A-6 | captured observation validates `CANONICAL_OBSERVATION_V1`; `opencnmv dataset validate` passes on the bootstrapped dataset |
| G3A-7 | variant semantics: ES-only vs ES+EN vs fallback are distinguished from evidence in the observation; counts per class reported |
| G3A-8 | substitution/complementary events produce correctly-scoped `version_event`/`event_affects` rows; no event silently widens or corrupts variant lifecycle |
| G3A-9 | extension taxonomies resolve with zero manual mappings: every new issuer-extension schema resolves from pinned taxonomy inputs or is `TAXONOMY_UNRESOLVED` |
| G3A-10 | IPP model families: credit/general/(fund) filings parse; modelo per filing recorded |
| G3A-11 | clean bootstrap: `init` on the expanded corpus → valid `COLUMNAR_DATASET_V1` |
| G3A-12 | convergence: a second capture+update on identical source state yields `NO_CHANGE` |
| G3A-13 | `compare` between the two observations reports only legitimate source-change classes — zero false divergences from translation/mapping |
| G3A-14 | determinism: two offline rebuilds of the expanded dataset are byte-identical (distinct PYTHONHASHSEED) |
| G3A-15 | expanded dataset is queryable: the G2-E read-only command battery works against it |
| G3A-16 | expected-vs-captured reconciliation: every freeze-inventory in-scope filing is captured or classified; zero unexplained omissions |
| G3A-17 | failure accounting: per-cause counts in the manifest; no fix was applied to convert a model failure into a pass |
| G3A-18 | regressions: G2-A…G2-G verifiers still pass on the frozen corpus |
| G3A-19 | no production import from `g0-r/`, `g1/`, `g2/`, `g3/` |
| G3A-20 | docs: CLI/docs/STATUS updated; manifest honest (state, inputs, outputs, hashes, findings, limitations) |

## Failure classification taxonomy

```text
UNIVERSE_ENUMERATION_FAILED  picker/listing surface failed or unparsable
IDENTITY_UNRESOLVED          missing registry row / LEI / name mismatch
DISCOVERY_AMBIGUOUS          picker match ambiguous for a denomination
SCOPE_EMPTY                  issuer has no filings in a declared family
ARTIFACT_MISSING             expected registry token/link absent
PARSE_FAILED                 Arelle/XML error on an artifact
TAXONOMY_UNRESOLVED          extension schema not resolvable offline
MODEL_VIOLATION              canonical observation/dataset validation fail
VARIANT_AMBIGUITY            es/en/fallback class undecidable from evidence
EVENT_UNSCOPED               substitution/complementary event unscopeable
SOURCE_CHANGED               hash/content drift between legs (source-side)
OTHER                        requires an explicit message
```

Every classified failure is counted in the manifest; `UNRESOLVED` is a
legitimate outcome — a heuristic patch applied to force `PASS` is itself
a gate failure (G3A-17).

## Capture protocol (filing leg)

- One `PoliteSession`, declared `OpenCNMV` user agent, sequential
  requests, min delay 2.5 s.
- Request bound for the whole gate (freeze + capture + re-capture):
  ≤ 2500 requests; actual counts recorded per leg.
- All response bytes preserved write-once under `evidence/` with sha256,
  `source_url`, `retrieved_at`, HTTP status.
- A second capture leg (same protocol) demonstrates convergence; hash
  drift is `SOURCE_CHANGED`, not a determinism failure.

## Explicitly out of scope

- All ~450 issuers: this gate falsifies generalisation on a fixed sample,
  it does not build the full universe (G3-B+).
- IP/OIR, participaciones, directivos, folletos, and any family outside
  IFA/IPP.
- Daily scheduling, releases, APIs, security master.
- Model V1 schema changes: anything unrepresentable is `UNRESOLVED`.
