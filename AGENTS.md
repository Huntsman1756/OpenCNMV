# AGENTS.md — OpenCNMV permanent rules

These rules are binding for every session. Read this file first. The large mission/contract
lives in `docs/PROJECT.md` and `docs/gates/G0-R.md`; this file is the operational rule set.

## 1. Source of truth

- **CNMV is the authoritative source.** Never treat a third-party mirror (including
  `filings.xbrl.org`, used only as `ESEF_EXTERNAL_ORACLE`) as primary.
- Preserve the **official original bytes** of every downloaded artefact, **unmodified**.
- Every downloaded artefact must have a **SHA-256** recorded.
- **Determinism = offline reproducibility.** Given the same raw inputs, the pipeline must produce
  identical outputs without network access.

## 2. Reuse over re-implementation

- **Adopt** mature OSS instead of writing custom parsers/downloaders.
- Arelle for XBRL 2.1 / Dimensions / Inline XBRL / ESEF validation / taxonomy packages / OIM.
- ESMA `esef_toolkit` for ESEF extraction, facts, dimensions, anchoring, presentation/calculation
  linkbases, historical versions, snapshots.
- `filings.xbrl.org` as **oracle only** for ESEF coverage checks.
- GLEIF for LEI identity and (where applicable) ISIN↔LEI mappings; do not assume 1:1 issuer↔ISIN.
- Before writing code, inspect relevant OSS, document the decision as
  `ADOPT / WRAP / EXTRACT / REFERENCE / REJECT`, and justify any code that replicates existing OSS.
- Preference: `existing OSS → thin adapter → OpenCNMV canonical model`, never a custom parser or a
  custom downloader framework.

## 3. Model invariants

- Never model a filing as one mutable document. Separate:
  `filing`, `filing_version`, `artifact`, `fact`.
- Preserve native XBRL semantics: **QNames, contexts, dimensions, units, decimals, periods**.
- Do **not** deduplicate facts by `concept + period_end` or `concept + period_start + period_end`;
  contexts and dimensions are part of the fact's semantic identity.
- Do not normalise or invent accounting equivalences without evidence.
- `submission_kind` and `submission_scope` belong to `filing_version`, not `filing`. They must be
  derived from evidence in the artefact and the applicable rules, **not** inferred from a date.
- **H2 ≠ FY/ESEF.** They are distinct regulatory obligations even when they share issuer / fiscal
  year / period_end. Preserve H2 `submission_scope` and all native contexts.
- Revisions (Circular 3/2018) must be handled with explicit semantics, not by hash comparison alone.

## 4. Corpus and scope (frozen)

- Issuers: **SAN** (Banco Santander), **BBVA**, **IBE** (Iberdrola).
- ESEF: **FY2024, FY2025**.
- IPP: **H1-2024, H2-2024, H1-2025, H2-2025, H1-2026**.
- **Q1/Q3 from 2021-05-03 are NOT required as IPP** (Ley 5/2021 removed former art.120 LMV).
  Do not label them `NOT_FOUND`; they are `NOT_REQUIRED_AS_IPP`. Voluntary quarterly after that
  date → OIR/IP → `OUT_OF_SCOPE_G0`.
- `NOT_FOUND` ≠ `NOT_REQUIRED`. Never conflate.
- Do not add issuers or document families outside the frozen corpus.

## 5. `expected_under_rule` (temporal correctness)

`expected_under_rule` must **not** depend only on Circular 3/2018. It must consider:

```text
rule
+ effective_from
+ effective_to
+ superior_law
+ filing_period
```

A superior-law change (e.g. Ley 5/2021 removing art.120) can suppress an obligation that the
Circular's text still describes. OpenCNMV must model this correctly.

## 6. Gates: states and honesty

- Only `PASS`, `FAIL`, or `NOT_APPLICABLE`. **No** `mostly-pass`, no `PASS with caveat`.
- If something cannot be demonstrated → `FAIL` (or, when truly applicable, `NOT_APPLICABLE`).
- A factual `FAIL` must **not** be dressed up to continue the project.
- Each gate directory must contain `README.md`, `evidence/`, and `manifest.json`.
  `manifest.json` fields: `gate`, `status`, `executed_at`, `code_commit`, `inputs`, `outputs`,
  `sha256`, `findings`, `limitations`.
- Do not advance to the next phase without the documented criteria being met.

## 7. Phase discipline

- G0-R is a **source, evidence, parsing and reproducibility probe**. Nothing more.
- During G0-R it is **forbidden**: frontend, dashboard, MCP, public REST API, generalisation to all
  issuers, ingesting IP/OIR / participaciones / autocartera / directivos / folletos / condiciones
  finales, building a security master, creating an own financial taxonomy, global IFRS
  normalisation, LLMs, AI summarisation, fuzzy matching (unless a demonstrated need),
  microservices, or cloud infrastructure.
- Execution order: **R0 → R4 first**; checkpoint `GO / HOLD / STOP`; only then R5 → R17.
- Do not run the 18 gates in parallel.

## 8. Checkpoint logic

`GO` only if: reuse is legally viable; discovery is reproducible; access mechanism is sufficiently
stable; artefacts are recoverable reliably. If any of these fails structurally, do not continue
automatically. A `GO` authorises G1 design, not a full platform.

## 9. Evidence discipline

- Raw bytes are immutable; never re-serialise before preserving the raw artefact.
- Record `source_url`, `retrieved_at`, HTTP metadata, `media_type`, `byte_size`, `sha256`.
- Never silently overwrite previously fetched bytes; a changed hash means the source changed.
- Keep dependency versions pinned (Arelle exact version, taxonomy package versions + SHA-256).

## 10. Session hygiene

- At the end of each session, update `docs/STATUS.md` (gates, checkpoint, blocking findings,
  next action).
- Prefer small, explicit dependencies. Do not build general infrastructure.

## 11. Authority and status separation

- `docs/STATUS.md` is **operational state only** (current gates, checkpoint, blocking findings,
  next action). It is a report, never the source of truth for criteria.
- The **authority** for gates, corpus, scope and acceptance criteria is `AGENTS.md` +
  `docs/gates/G0-R.md` (+ `docs/PROJECT.md` for the model). Never change criteria to make a gate
  pass, and never redefine a gate by editing `STATUS.md` first.
- A gate verdict is decided against `docs/gates/G0-R.md`; `STATUS.md` merely records it.
