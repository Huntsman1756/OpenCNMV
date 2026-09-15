# Finding 0002 — IPP H2 contains dual temporal contexts (current-half vs YTD)

- **Date:** 2026-09-14
- **Status:** Accepted (relevant to R17 and the fact canonicalisation rule)
- **Scope:** R17 (H2 vs ESEF period reconciliation); fact identity / `period_role`

## Summary

In the IPP H2 report for BANCO SANTANDER, S.A. (nreg `2026029523`, H2-2025), two XBRL contexts
appear **simultaneously** and **both end on 2025-12-31**, but with different temporal semantics:

```text
Dcur_PeriodoCorrienteActualMiembro
    entity: BANCO SANTANDER, S.A.
    period: 2025-07-01 -> 2025-12-31     (current half-year, H2-2025)

Dcur_AcumuladoActualMiembro
    entity: BANCO SANTANDER, S.A.
    period: 2025-01-01 -> 2025-12-31     (YTD / accumulated annual)
```

(The current-half context also appears as `Dcur_ORICPeriodoCorrienteActualMiembro`.)

## Implication

A fact cannot be reduced to `concept + period_end`. Both contexts end on the same date
(2025-12-31) but represent **different temporal semantics** (current half vs YTD). This is the
exact proof that the canonicaliser must key a fact by its **context (incl. dimensions)** and derive
`period_role` (e.g. `CURRENT_HALF` vs `YTD`) as DERIVED data with provenance to the native context.

This is a key input to **R17** (H2 vs ESEF period reconciliation) and to the fact model.

## Evidence

- `g0-r/R07-raw-retrieval/evidence/ipp-SAN-II-semestre-de-2025.zip` (SAN H2-2025 IPP XBRL)
- `g0-r/R09-taxonomy-discovery/evidence/taxonomy_matrix.json`
