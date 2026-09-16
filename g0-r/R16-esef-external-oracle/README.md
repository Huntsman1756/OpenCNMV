# R16 — ESEF_EXTERNAL_ORACLE_RECONCILIATION

**Gate:** R16 — ESEF_EXTERNAL_ORACLE_RECONCILIATION
**Status:** `PASS` (all divergences reconciled or explicitly attributed; 2 coverage
findings opened)
**Executed:** 2026-09-16 (UTC)
**Oracle:** `filings.xbrl.org` (JSON:API). Oracle-only, never authoritative —
its docs explicitly state the index is **not complete** and that its xBRL-JSON
is **Arelle-generated**, so fact comparison is labelled
`DATA_PROJECTION_CROSSCHECK`, not independent-parser validation.

## Reconciliation key

```text
LEI + period_end + filing_system=ESEF + country=ES (CNMV source)
variants resolved via: language tag, package sha256, date_added, oracle filing id
```

Full LEI filing history was fetched for all three issuers (not just the target
periods), satisfying the "whole history around the period" rule.

## Comparison ladder

```text
L1  CNMV package sha256 == oracle package sha256
L2  member paths + member sha256 (repackaging tolerance)
L3  iXBRL report-member sha256
L4  canonical fact multiset (oracle OIM vs our committed R11 OIM;
    key = oim_fact_key + decimals + nil + sha256(value))
```

## Result matrix

| Filing      | Oracle ES candidate | L1 pkg | Members | iXBRL | Facts | Verdict |
|-------------|--------------------|--------|---------|-------|-------|---------|
| IBE FY2024  | `…-20241231-es`    | ==     | ==      | ==    | ==    | **EXACT_PACKAGE_MATCH** |
| SAN FY2024  | `…-20241231-en`    | ≠      | 0 shared| 0     | ≠     | **OPEN_CNMV_POSSIBLE_OMISSION** |
| BBVA FY2024 | `…-20241231-0-en`  | ≠      | 0 shared| 0     | ≠     | **OPEN_CNMV_POSSIBLE_OMISSION** |
| SAN FY2025  | none (ES)          | —      | —       | —     | —     | **ORACLE_OMISSION** |
| BBVA FY2025 | none (ES)          | —      | —       | —     | —     | **ORACLE_OMISSION** |
| IBE FY2025  | none (ES)          | —      | —       | —     | —     | **ORACLE_OMISSION** |

`unexplained_divergences = 0` → **R16 = PASS**.

## Findings

1. **IBE FY2024 — exact end-to-end match.** Oracle package sha256
   (`89DFD3EF…`) is byte-identical to the CNMV raw artifact sha256 recorded in
   R7; member manifest, iXBRL member and the 833-fact OIM multiset all equal.
   Proves the oracle ingests CNMV bytes unchanged for this filing.

2. **Language-variant parallel submissions (SAN, BBVA FY2024).** CNMV
   ListadoIFA exposes exactly **one** `Fichero ZIP` link per registro — the
   `-es` package we hold. The oracle's ES filing is a **different package**:
   `-en` language variant (different iXBRL doc, language-parallel extension
   taxonomy — translated concept/member names; SAN additionally changes
   extension namespace `www.santanderbank.com` → `www.santander.com`). These
   are distinct OAM submissions of the same underlying report:
   - shared ifrs-full undimensioned numeric core: SAN 458/674 (68%),
     BBVA 522/884 (59%) — the rest differ only via translated extension
     concept/member QNames;
   - BBVA-2021 shows the oracle indexing **both** (ES-0=`-en`, ES-1=`-es`),
     proving both variants reach CNMV's OAM feed; for 2022+ the oracle kept
     only `-en`.
   - Verdict `OPEN_CNMV_POSSIBLE_OMISSION`: our corpus holds the
     ListadoIFA-exposed `-es` artifact; the `-en` OAM submission is a real
     CNMV-sourced ESEF report for the same issuer+period not covered by our
     discovery surface. Opened as a coverage finding for the G0-R verdict.

3. **Same-key value diffs (2 total, both documented):**
   - SAN `ifrs-full:DividendsRecognisedAsDistributionsToOwnersPerShare` 2024:
     `-en` `"0.10"` vs `-es` `"0.1"` — lexical form only, numerically equal.
   - BBVA `ifrs-full:Equity` @ 2023-01-01 with
     `RetrospectiveApplicationAxis=FinancialEffectOfChangesInAccountingPolicyMember`:
     `-en` **-98,000,000** vs `-es` **+98,000,000** — a real sign difference
     between the two language submissions of the same dimensioned fact.
     Recorded verbatim in `reconciliation.json`; it is a content divergence
     **between issuer submissions**, not an OpenCNMV processing artifact.

4. **FY2025 ES omissions ×3.** No ES/ESEF filing exists in the oracle for any
   of the three issuers' 2025-12-31 period. Historical cadence (ES-2024
   filings added ~May-2025; SAN GB-2025 added 2026-03-04) indicates ingestion
   lag consistent with the oracle's stated incompleteness — `ORACLE_OMISSION`,
   not an OpenCNMV error. SAN's own FY2025 `-en`/GB package exists under FCA
   (`…-2025-12-31.xbri`), i.e. the report exists; the CNMV ES row is simply
   not yet indexed.

5. **Cross-authority diagnostic.** SAN GB-2024/GB-2025 packages share **zero**
   members with the CNMV packages — distinct FCA submissions, no silent
   dedup/reuse. Also observed: oracle `sha256` field == sha256 of the served
   package zip (verified on every download).

## Limitations

- The `-en` packages' CNMV provenance is inferred (ES country code + IBE
  byte-identical precedent + naming convention); the oracle does not expose a
  per-filing source URL. Whether CNMV's public surfaces beyond ListadoIFA
  expose them was not exhaustively probed.
- The OIM cross-check compares Arelle projections on both sides
  (`DATA_PROJECTION_CROSSCHECK`) — it detects input/versioning differences,
  it does not independently validate Arelle.
- Oracle metadata (counts, dates) reflects its index state at execution time.

## Evidence

- `r16_reconcile.py` — reconciler (API snapshot → downloads → L1–L4 → verdicts)
- `evidence/oracle_filings_{SAN,BBVA,IBE}.json` — full LEI filing history
- `evidence/oracle_downloads/` — oracle packages + OIM JSON (sha256 recorded)
- `evidence/reconciliation.json` — full matrix, member manifests' digests,
  numeric-core metrics, same-key value diffs
