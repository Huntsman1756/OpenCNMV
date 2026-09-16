# R17 — H2_VS_ESEF_PERIOD_RECONCILIATION

**Gate:** R17 — H2_VS_ESEF_PERIOD_RECONCILIATION (final G0-R gate)
**Status:** `PASS`
**Executed:** 2026-09-16 (UTC)

## Objective

Per `docs/gates/G0-R.md` — demonstrate: (1) H2 ≠ FY/ESEF filings; (2) they can
share issuer + fiscal year + period_end; (3) H2 `submission_scope` preserved;
(4) all native XBRL contexts preserved; (5) `CURRENT_HALF != YTD` when the
source distinguishes them; (6) dimensions not collapsed; (7) an H2 revision
caused by the IFA can be represented; (8) fact comparison ≠ semantic
equivalence; (9) second-semester vs annual-cumulative duality preserved.

Six pairs: `{SAN, BBVA, IBE} × {H2-2024↔FY2024, H2-2025↔FY2025}`.
H1-2026 excluded — no FY2026 exists yet.

## Result matrix (all six pairs)

| Pair | H2 nreg | FY registro | same period_end | scope | ctx | expl/typed dims | CUR facts | YTD facts | naive coll. | canon coll. |
|------|---------|-------------|-----------------|-------|-----|-----------------|-----------|-----------|-------------|-------------|
| SAN  2024 | 2025031125 | 20509 | yes | HYBRID_OR_REFERENCED | 120 | 130/1 | 145 | 486 | 523 | 0 |
| SAN  2025 | 2026029523 | 20875 | yes | HYBRID_OR_REFERENCED | 120 | 130/1 | 147 | 500 | 532 | 0 |
| BBVA 2024 | 2025023010 | 20448 | yes | HYBRID_OR_REFERENCED | 120 | 130/1 | 117 | 296 | 379 | 0 |
| BBVA 2025 | 2026023406 | 20854 | yes | HYBRID_OR_REFERENCED | 120 | 130/1 | 116 | 295 | 378 | 0 |
| IBE  2024 | 2025031737 | 20515 | yes | FULL | 96 | 106/15 | 70 | 239 | 265 | 0 |
| IBE  2025 | 2026031470 | 20934 | yes | FULL | 96 | 106/15 | 71 | 244 | 272 | 0 |

## How each gate point is discharged

1. **Distinct filings** — H2 carries an IPP `nreg` (e.g. `2026029523`), FY an
   IFA `registro oficial` (e.g. `20875`); different families, different
   registries, different artifacts, different taxonomies. `distinct_filing_identity`
   + `distinct_registries` PASS.
2. **Shared issuer + FY + period_end** — every pair shares the fiscal close
   (`same_period_end` PASS; Arelle-exclusive-end representation, e.g.
   `2026-01-01` ≡ 2025-12-31 close, identical convention on both sides).
3. **`submission_scope` from declared content, not inference** — IPP
   instances self-declare `Modelo` + `Estadistico`: SAN/BBVA
   `Modelo=ECR, Estadistico=S` → `HYBRID_OR_REFERENCED` (statements +
   statistical annexes); IBE `Modelo=GEN, Estadistico=N` (+ embedded complete
   report) → `FULL`. No `UNKNOWN` needed.
4. **All native contexts preserved** — per-filing context counts and
   explicit/typed dimension counts carried verbatim from the R12 evidence.
5. **`CURRENT_HALF != YTD`** — proven structurally: e.g. SAN-H2-2025 holds
   `2025-07-01→2026-01-01` (147 facts) **and** `2025-01-01→2026-01-01`
   (500 facts) — same `period_end`, different semantics — plus prior-year
   comparatives of both kinds.
6. **Dimensions not collapsed** — explicit dims (106–130 contexts/filing) and
   typed dims preserved (IBE: 15 typed-dim contexts).
7. **H2 revision representable** — `revision_event{event_type=H2_RESUBMISSION,
   creates_version_transition=true, trigger=ANNUAL_ACCOUNTS_FORMULATION}`
   with two evidence levels kept separate: `NORMATIVE_RULE` (Circular 3/2018:
   differences appearing at annual-accounts formulation oblige re-sending H2
   referencing the IFA) and `SOURCE_OBSERVED` (Metrovacesa: H2-2025 reg.
   39018 and IFA-2025 reg. 39038 on 24/02/2026, then H2 modification reg.
   39246 on 26/02/2026 — captured page preserved; the trigger is **not**
   asserted to be IFA-caused since the document does not say so).
8. **Fact comparison ≠ semantic equivalence** — diagnostic only: concept URI
   sets are disjoint by construction (`www.cnmv.es/xbrl/ipp/*` vs
   `ifrs-full/*` + issuer extension namespaces); `shared_concept_uris = 0` in
   all six pairs. No IPP↔IFRS concept mapping attempted — that would be
   dangerous at G0.
9. **Duality preserved** — CURRENT_HALF and YTD families coexist in every H2
   filing with prior-year comparatives of both kinds.

## Adversarial control

```text
naive key   = concept + period_end
            -> 265–532 collisions per filing: CURRENT_HALF, YTD *and*
               close-instant facts collapse onto one key (semantic loss)

canonical   = concept + native context (entity|period|dims) + unit
              + decimals + lang + value_sha256
            -> 0 collisions in all six H2 filings
```

`concept + period_end` is falsified as an identity key — the strongest single
piece of evidence that contexts/dimensions are part of a fact's semantic
identity.

## Limitations

- `submission_scope` vocabulary is derived from the declared `Modelo` +
  `Estadistico` fields; ECR is labelled `HYBRID_OR_REFERENCED` because the
  template bundles statements with statistical annexes — documented, not
  inferred from size.
- The Metrovacesa fixture demonstrates the H2-modification event exists in
  source; the normative IFA→H2 trigger is asserted only at
  `NORMATIVE_RULE` level (no corpus H2 revision exists — all corpus H2 rows
  are unmodified originals).
- Fact-level comparison between H2 and ESEF remains a diagnostic; no
  canonical concept mapping is claimed.

## Evidence

- `r17_reconcile.py` — pair-matrix builder + checks
- `evidence/r17_results.json` — full matrix, period families, collision
  counts, scope evidence, revision model, 11 gate checks, verdict
- `evidence/metrovacesa-oir-r17.html` — captured CNMV OIR page (sha256
  `B98C1F6F…`) backing the SOURCE_OBSERVED fixture
