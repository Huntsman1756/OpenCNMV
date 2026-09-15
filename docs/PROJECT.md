# PROJECT.md — OpenCNMV mission and conceptual model

This is the stable mission and conceptual contract for OpenCNMV. The frozen corpus and the gate
definitions live in `docs/gates/G0-R.md`. The operational rule set lives in `AGENTS.md`.

## Mission

Build **OpenCNMV**, an open, reproducible and auditable layer over official financial information
of issuers published by the CNMV.

OpenCNMV does **not** aim to build a complete "Spanish EDGAR", nor to replace CNMV, ESAP,
filings.xbrl.org, Arelle or ESMA `esef_toolkit`.

Its differentiating value is:

> **CNMV official-source-first + identity + immutable raw artefacts + revision semantics +
> native XBRL facts + reproducible datasets.**

Before any product, API, MCP, interface or general-purpose infrastructure, a
**G0-R — CNMV Source & Reproducibility Probe** must be executed and closed.

## Conceptual model

Do not model a filing as a single mutable document. Separate four concepts:

### `filing`
The regulatory/economic slot or obligation.

```text
id
issuer_id
reporting_slot      # Q1 | H1 | Q3 | H2 | FY
period_start
period_end
regulatory_regime
```

### `filing_version`
What was actually filed/published in a given observation.

```text
id
filing_id
source
source_registration_no
submission_kind
submission_scope
filed_at
source_updated_at
observed_at
supersedes_version_id
```

- `submission_kind` examples: `INTERIM_MANAGEMENT_STATEMENT`, `QUARTERLY_FINANCIAL_REPORT`,
  `SEMIANNUAL_REPORT`, `ANNUAL_ESEF`, `UNKNOWN`.
- `submission_scope` examples: `FULL`, `STATISTICAL_ONLY`, `HYBRID_OR_REFERENCED`, `UNKNOWN`.
- `submission_kind` / `submission_scope` belong to `filing_version`, **not** `filing`, because a
  revision can change the submission kind (e.g. `INTERIM_MANAGEMENT_STATEMENT` → `QUARTERLY_
  FINANCIAL_REPORT`).
- Do not infer `submission_scope` only from the IFA publication date. Derive it from the
  artefact evidence and the applicable rules.

### `artifact`
The exact bytes obtained from the source.

```text
id
filing_version_id
role
media_type
source_url
retrieved_at
sha256
byte_size
```

Raw bytes are immutable.

### Source identity hierarchy (observed, feeds R6)

```text
IPP  canonical source identity = nreg
ESEF canonical source identity = registro oficial
artifact locator              = webservices/verdocumento/ver?e=<token>   (stable)
ephemeral transport locator   = descargaxbrlipp.ashx?t={GUID}            (never identity)
```

- `source_registration_no` = `nreg` (IPP) / `registro oficial` (ESEF).
- The per-artefact locator is the stable `?e=` token.
- The IPP `?t={GUID}` is **ephemeral** (changes per visit) and must never be used as identity;
  it is only a discovery/redirect parameter.

### `fact`
Preserve the native XBRL fact (do **not** create a normalised SEC-style companyfacts yet).

```text
fact
  filing_version_id
  taxonomy_namespace
  concept_qname
  value
  unit
  decimals
  context_id
  period_start
  period_end
  instant
  dimensions
  source_fact_id
```

- Never deduplicate solely by `concept + period_end` or `concept + period_start + period_end`.
  Contexts and dimensions are part of the fact's semantic identity.
- If a `period_role` is later derived (`CURRENT_HALF`, `YTD`, `COMPARATIVE_HALF`,
  `COMPARATIVE_YTD`, `INSTANT`), it must be stored as **DERIVED** data with provenance to the
  original XBRL context.

## Revisions semantics

Circular 3/2018 provides explicit semantics for modifications. Do not assume hash comparison is
enough. R13 must distinguish:
- `13A REVISION_EXISTS`
- `13B REVISION_TARGET_EXACT`
- `13C REVISION_SEMANTICS_EXTRACTED`

For `13C`, extract where present: `nature`, `reason`, `adjustment_amount`, `affected_periods`,
`annual_accounts_trigger`, `referenced_annual_filing`. Do not declare an exact `amendment_chain`
until the binding between revision and prior submission can be recovered unambiguously. A
revision may change even `submission_kind`.

## H2 versus IFA/ESEF

Do not deduplicate them. They may share `issuer`, `fiscal_year`, `period_end`, but they are
different regulatory obligations/documents. The H2 may also exist with a different scope
(`FULL` / `STATISTICAL_ONLY` / `HYBRID_OR_REFERENCED` / `UNKNOWN`), and may contain distinct
contexts for: second semester, cumulative of the year, comparatives, instants. Preserve them all.

```text
H2 != FY/ESEF
```

## Reuse and dependencies

| OSS / source | Role |
|---|---|
| **Arelle** | XBRL 2.1, Dimensions, Inline XBRL, ESEF validation, taxonomy packages, OIM JSON/CSV. No custom XBRL parser. |
| **ESMA esef_toolkit** | ESEF extraction, facts, dimensions, anchoring, presentation/calculation linkbases, historical versions, snapshots. |
| **filings.xbrl.org** | `ESEF_EXTERNAL_ORACLE` only — coverage checks, omission/discrepancy detection. Never primary. |
| **GLEIF** | LEI identity; where applicable ISIN↔LEI mappings. Do not assume 1:1 issuer↔ISIN. |

Preferred design:

```text
existing OSS → thin adapter → OpenCNMV canonical model
```

## Regulatory-temporal correctness

`expected_under_rule` depends on `rule + effective_from + effective_to + superior_law +
filing_period`. A superior-law change can suppress an obligation that the Circular's text still
describes. This is the core temporal problem OpenCNMV must model.

## Scope restriction (during G0-R)

Forbidden during G0-R: frontend, dashboard, MCP, public REST API, generalisation to all issuers,
ingesting IP/OIR / participaciones / autocartera / directivos / folletos / condiciones finales,
building a security master, own financial taxonomy, global IFRS normalisation, LLMs, AI
summarisation, fuzzy matching (unless demonstrated need), microservices, cloud infrastructure.
G0-R is a probe of source, evidence, parsing and reproducibility. Nothing more.
