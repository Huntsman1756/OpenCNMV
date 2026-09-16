# G1-B — DUAL_LANGUAGE_CAPTURE + CROSS-VARIANT FACT COMPARISON

**Status:** PASS (8/8 checks)

G1-B extends the G0 deterministic contract to both UI-language views of each
in-scope ESEF registro and produces the first cross-variant fact dataset: it
detects divergent submissions without ever merging variants, designating one
as truth, or letting a UI fallback masquerade as a variant.

Pipeline (three stages, one verifier):

```text
g1b_capture.py --run A|B   online:  POST busqueda?id=25 per issuer x lang,
                           resolve document tokens, download ESEF package,
                           prefix-probe viewer docs (256 KiB, language marker)
g1b_extract.py 1|2         offline: Arelle 2.44.0 parse of every UNIQUE
                           variant package (10), pinned R10 taxonomies,
                           ESEF validation, OIM export, Control A
g1b_compare.py             pure:    cross-variant fact comparison + checks
g1b_verify.py              determinism: capture A==B, extract run1==run2,
                           dataset rebuild identical
```

## Identity model proven

```text
variant_artifact_set_id = sha256(canon([["ESEF_PACKAGE_ZIP_XBRL", pkg_sha]]))
```

Artifact sets deduplicate by officially served **content**, never by
`requested_ui_language`. Per filing per view the inventory records
`requested_ui_language`, `resolved_submission_language`, `resolution_mode`
(`SUBMITTED_VARIANT` | `FALLBACK_TO_ES`), `variant_artifact_set_id`, package
sha256, and a `preserved_reference` cross-check proving the freshly served
bytes are identical to the canonical evidence (R7 `-es` / G1-A `-en`).

| Filing | submitted variants | en-view mode |
|---|---|---|
| SAN FY2024 / FY2025 | 2 (es, en) | SUBMITTED_VARIANT |
| BBVA FY2024 / FY2025 | 2 (es, en) | SUBMITTED_VARIANT |
| IBE FY2024 / FY2025 | 1 (es) | FALLBACK_TO_ES |

Adversarial control (preregistered): the **bad model** —
`requested_ui_language` as variant identity — yields 2 variants for every
filing including IBE (a phantom EN). The artifact-set identity model yields
IBE=1. The check asserts both, turning the G1-A discovery into a tested
invariant.

Viewer-doc evidence: prefix probes show SAN/BBVA `lang=en` views serve
English XHTML viewers (`xml:lang="en"`, English titles). For IBE the en-view
locators serve Spanish documents — FY2024 PDFs carry `/Lang (es)`; the ZIP
document token for IBE is literally the *same token* across both views
(`token_zip_identical_across_views=true`). The fallback is total, not just
the package.

## Fact keys

```text
native_fact_key    = concept | entity | period | dims | unit | lang
cross_variant_key  = native_fact_key minus lang
fact_payload       = value, decimals, nil, value_sha256   (never identity)
```

Comparison modes: issuer-extension concepts → `UNMAPPED_VARIANT_FACT`;
language-sensitive types (string/normalizedString/token/lang/textBlock)
→ `LANGUAGE_SENSITIVE_NOT_COMPARED` when paired, `VARIANT_ONLY_FACT` when
one-sided; everything else compares payloads:

```text
MATCH_EXACT | MATCH_NUMERIC_EQUIVALENT | DIVERGENT_SUBMISSION_FACT
| VARIANT_ONLY_FACT
```

## Results

| Filing | EXACT | NUM_EQ | DIVERGENT | VARIANT_ONLY | LANG_SENS | UNMAPPED |
|---|---|---|---|---|---|---|
| SAN FY2024 | 848 | 0 | 0 | 834 | 182 | 1008 |
| SAN FY2025 | 907 | 1 | 0 | 744 | 180 | 984 |
| BBVA FY2024 | 896 | 0 | **1** | 464 | 161 | 1114 |
| BBVA FY2025 | 898 | 0 | 0 | 411 | 160 | 1133 |
| IBE FY2024/25 | — | — | — | — | — | — (skipped, 1 variant) |

**Mandatory positive test — PASS.** `ifrs-full#Equity`, LEI
`K8MS7FD7N5Z2WQ51AZ71`, instant 2023-01-01, dim
`RetrospectiveApplicationAndRetrospectiveRestatementAxis =
FinancialEffectOfChangesInAccountingPolicyMember`: es `+98000000`,
en `-98000000` → `DIVERGENT_SUBMISSION_FACT`. Same structural fact, two
officially submitted values.

**Numeric-equivalence control — PASS.** `ifrs-full#DilutedEarningsLossPerShare`
SAN-FY2025: es `0.9` vs en `0.900` → `MATCH_NUMERIC_EQUIVALENT` (lexical-only
difference, no false divergence). Note on the R16 oracle case
(`DividendsRecognisedAsDistributionsToOwnersPerShare` 0.1/0.10): it does not
reproduce on CNMV bytes because the official CNMV `-en` package carries
`0.1`, identical to `-es` (MATCH_EXACT). The `AC7D667F…` oracle package is
**not** a CNMV `-en` variant — it is Santander's `ESEF-GB-0` filing to the
FCA, a different authority's submission and out of cross-variant scope. The
ES picture is unchanged: CNMV ES `-en` = `77ac614a…`, filings.xbrl.org ES
SAN-FY2025 = absent → R16's `ORACLE_OMISSION` stands.

**IBE negative control — PASS.** `submitted_variant_count=1`, en-view
resolves `es` (`FALLBACK_TO_ES`), identical artifact set, comparison skipped,
zero divergences, no phantom EN variant.

## Findings that matter for the model

1. **Extension namespaces genuinely differ across variants.** SAN-FY2024:
   `-es` uses `santanderbank.com/20241231`, `-en` uses `santander.com/20241231`.
   BBVA and SAN-FY2025 share the *same* extension namespace across variants —
   yet **zero extension QNames are shared** (the `-en` schema renames element
   local names to English). `qname_in_both_variants=0` over 4,239 extension
   facts → `UNMAPPED_VARIANT_FACT` is not merely conservative, it is the only
   defensible class; no translation heuristics were built.
2. **VARIANT_ONLY is dominated by extension-membered dimensions** (2,448 of
   2,453; flagged `extension_dim_member` in the dataset): ifrs-full concepts
   dimensioned by issuer members cannot pair because member identity lives in
   a different extension namespace per variant. Only 5 VARIANT_ONLY facts are
   free of extension dim members.
3. **Language-sensitive textual facts are never false divergences** — 683
   pairs classified `LANGUAGE_SENSITIVE_NOT_COMPARED`, 0 divergences among
   them.
4. Viewer roles are not homogenous: IBE's COVER/CONSOLIDATED locators serve
   PDFs (informe anual), not iXBRL — recorded `media_hint` per probe.

## Checks (all PASS)

| check | result |
|---|---|
| bbva_equity_98m_divergent | es +98M / en −98M → DIVERGENT |
| san_numeric_equivalent_0_10_vs_0_1 | lexical-only → MATCH_NUMERIC_EQUIVALENT |
| ibe_no_phantom_en_variant | 1 variant, fallback, 0 divergences |
| no_language_sensitive_divergence | 0 |
| adversarial_bad_model_fails | UI-lang identity ⇒ phantom IBE EN; set identity ⇒ 1 |
| capture_inventory_core_equal | runA == runB (`7fe9de03…`) |
| extraction_facts_identical | 10/10 facts.jsonl sha equal run1==run2 |
| comparison_dataset_deterministic | dataset sha stable across rebuild |

## Evidence layout

- `evidence/capture/run{A,B}/` — 12 search pages each, `variant_inventory.json`,
  `inventory_core_sha256.txt`, `viewer-prefixes/` (hashed 256 KiB probes).
- `evidence/parse/run1/` — per unique variant: `.facts.jsonl`,
  `.model_summary.json`, `.arelle-log.json`, `.oim.json.gz`,
  `extract_results.json` (offline, ioerr=0, Control A multiset equal 10/10).
- `evidence/compare/` — per dual-variant filing `.comparison.jsonl` +
  `g1b_divergence_dataset.json` + `g1b_compare_results.json`.
- `evidence/g1b_results.json` — gate verdict and check matrix.
- `_runs/` (gitignored) — downloaded run packages (sha-verified against
  preserved canonical bytes) and extraction run2 rebuild.

## Limitations

- `variant_artifact_set_id` covers the canonical ESEF report package; viewer
  documents are recorded as locators + resolved-language prefix probes, not
  preserved whole (same scoping as G1-A; IBE's en-view is proven Spanish at
  the document-language level).
- Lifecycle ordering remains undistinguished (per G1-A): a variant-only
  substitution event is still the falsification target — not in scope here.
- Extension-concept cross-variant mapping is deliberately unresolved
  (`UNMAPPED_VARIANT_FACT`); a justified mapping (e.g. via anchoring
  relationships to ifrs-full concepts) is future work.
