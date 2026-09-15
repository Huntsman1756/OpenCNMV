# R11 — ESEF_ARELLE_PARSE

**Gate:** R11 — ESEF_ARELLE_PARSE
**Status:** `PASS`
**Executed:** 2026-09-15 (UTC)

## Objective

Per `docs/gates/G0-R.md`: *"Demonstrate ESEF parsing with Arelle. No alternative parser unless
documented Arelle failure. Verify preservation of concepts, contexts, units, dimensions,
decimals, facts."*

R11 is executed as a **conformance/integration test over Arelle**, not a custom extractor:

```text
ESEF_PACKAGE_ZIP_XBRL  (raw bytes, R7)
          |
        Arelle 2.44.0  (pinned, R10)
          |
   +------+-------+
   |              |
ModelXbrl      saveLoadableOIM
Python API     xBRL-JSON
   |              |
   +--- compare --+          <- CONTROL A
          |
   OpenCNMV evidence
```

## Runtime

- `arelle-release == 2.44.0` (Python API, `arelle.api.Session`), CPython 3.12.
- `internetConnectivity="offline"` — every run proves zero network need (`ioerr=0`, zero
  download attempts in the log).
- Taxonomy packages pinned in R10, loaded via `packages`: ESMA ESEF `2022 v1.1` (FY2024) or
  `2024` (FY2025) + locally-assembled IFRS `full_ifrs` + xbrl.org LEI packages (transitive
  imports of `esef_cor.xsd`; see R10 addendum).
- `plugins="validate/ESEF|saveLoadableOIM"`, `validate=True`, `keepOpen=True`.
- Disclosure system: `esef-2022` for FY2024 filings, `esef-2024` for FY2025 filings
  (each package load tested in its own session — loading both ESMA packages at once raises
  `tpe:packageRewriteOverlap` on `taxonomy/ext/`).
- Issuer extension taxonomies resolve from the preserved report package itself.

## Corpus — six ESEF report packages (R7 `ESEF_PACKAGE_ZIP_XBRL`)

SAN / BBVA / IBE × FY2024 / FY2025.

## Results (`evidence/r11_results.json`, per-filing `*.model_summary.json`)

| Filing | facts | contexts | units | concepts (DTS) | DTS docs | ioerr | Control A |
|---|---|---|---|---|---|---|---|
| SAN-FY2024 | 1951 | 329 | 2 | 5575 | 84 | 0 | true |
| BBVA-FY2024 | 1847 | 183 | 2 | 5597 | 84 | 0 | true |
| IBE-FY2024 | 833 | 59 | 2 | 5529 | 84 | 0 | true |
| SAN-FY2025 | 1952 | 329 | 2 | 5651 | 88 | 0 | true |
| BBVA-FY2025 | 1830 | 155 | 2 | 5667 | 88 | 0 | true |
| IBE-FY2025 | 869 | 59 | 2 | 5615 | 88 | 0 | true |

Preservation demonstrated per filing (`*.facts.jsonl`, deterministic one-line-per-fact inventory):

- fact QName, raw value / xValue, decimals, nil state
- context: entity scheme+identifier, period (start/end/instant/forever)
- explicit dimensions (QName→member) and typed dimensions (QName→typed value)
- unit (measures, numerator/denominator)
- `xml:lang` where present; fact-footnote relationship count

## CONTROL A — Arelle Python API vs Arelle OIM export

Same session produces (a) `ModelXbrl` API extraction and (b) standard xBRL-JSON via Arelle's own
`saveLoadableOIM` plugin. Both are normalised to a semantic fact key
`(concept-QName | entity scheme+id | start/end/instant/forever | unit | E:explicit/T:typed
dimensions | language)` and compared as **multisets** — invariants, not serialized bytes.

All six filings: `fact_count` equal, `fact_multiset_equal=true`, `concept_coverage_equal=true`,
decimals/nil distributions equal, `nil_count` equal. Control A **passes** — the adapter loses
nothing relative to Arelle's standard OIM serialization.

## CONTROL B — Arelle vs Brel (independent oracle, SAN-FY2025 only)

`brel-xbrl==0.8.2a1` in the isolated `.venv-brel` (its dependency pins conflict with the main
environment; it is never installed globally). `r11_control_b.py`, result in
`evidence/control_b_brel.json`:

| Metric | Arelle | Brel |
|---|---|---|
| facts | 1952 | 1640 |
| distinct context signatures | 329 | 7 |
| concepts reported | 403 | 363 |
| facts with dimensions | 1095 | 0 |

- Brel's reported concept set is **fully contained** in Arelle's (`concepts_only_brel=0`,
  `concepts_common=363`); no concept exists in Brel that Arelle missed.
- Brel's lower counts are **Brel limitations, not Arelle findings**: Brel drops facts without an
  iXBRL `format` attribute (`Fact format None not yet supported by XBRL`, repeated in its log)
  and does not surface explicit dimensions in its fact model (all 1640 Brel facts report zero
  dimensions, and only 7 context signatures vs 329).
- Conclusion: **structural agreement at concept level; Brel is a usable second oracle for
  presence/absence of concepts but is not authoritative and cannot be used for fact-level
  equivalence.** Arelle remains the single authoritative engine; no documented Arelle failure
  occurred, so no alternative parser is required.

## ESEF validation findings (filing-level, not parser failures)

`validate/ESEF` runs on every filing; log codes are preserved per filing in
`*.arelle-log.json` and counted in `*.model_summary.json` (`log_code_counts`). Typical entries
are filing findings (e.g. `ESEF.RTS.Annex.II.Par.2.missingMandatoryMarkups`,
`ESEF.2.7.1.targetXBRLDocumentWithFormulaWarnings`,
`ESEF.2.6.1.reportIncorrectlyPlacedInPackage`) — properties of the issuer filings, not load
failures. `ioerr=0` on all six.

## Findings

1. **The six ESEF packages load fully offline** with the R10-pinned taxonomy set; DTS resolves
   completely (84/88 documents; FY2025 pulls the 2024-03-27 IFRS+LEI sets). No `missingReferences`
   once IFRS/LEI transitive deps are pinned — that discovery itself amended R10.
2. **Concept coverage is complete**: Arelle's DTS contains 5529–5667 concepts per filing across
   `xbrl.ifrs.org` (~5300), issuer extension (~60–100), ESMA and xbrl.org namespaces.
3. **All contexts in the corpus use explicit dimensions only** (`contexts_typed_dims=0` across
   the six filings; 54–439 explicit-dimension contexts per filing). The typed-dimension code
   path is implemented and exercised by Control A normalization even though the frozen corpus
   does not trigger it.
4. **Brel is a partial oracle only** — useful to bound Arelle's concept coverage, incapable of
   fact-level parity on these filings.

## Limitations

- `saveLoadableOIM` emits xBRL-JSON; OIM-CSV equivalence is covered transitively (both are
  serializations of the same Arelle model).
- Fact footnote relationships are counted but not yet extracted into the inventory
  (0 observed across the six filings).
- Brel comparison covers one representative filing (SAN-FY2025) per the gate design.

## Evidence

- `r11_parse.py` — harness (one Arelle `Session` per filing).
- `r11_control_b.py` — Brel oracle comparison.
- `evidence/<FID>.facts.jsonl` — deterministic API fact inventory (sha256 in model_summary).
- `evidence/<FID>.model_summary.json` — counts, namespaces, log codes, offline evidence,
  Control A verdict, output hashes.
- `evidence/<FID>.oim.json.gz` — Arelle `saveLoadableOIM` xBRL-JSON export.
- `evidence/<FID>.arelle-log.json` — Arelle log records (level, messageCode, message).
- `evidence/r11_results.json` — aggregate results.
- `evidence/control_b_brel.json` — Arelle vs Brel on SAN-FY2025.
