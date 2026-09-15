# Finding 0001 — Q1/Q3 post-2021-05-03 are not required as IPP

- **Date:** 2026-09-14
- **Status:** Accepted (affects `expected_under_rule` and the frozen corpus)
- **Scope:** G0-R corpus definition; `availability_matrix`; `expected_under_rule`

## Summary

Ley 5/2021 removed former art.120 of the LMV (Real Decreto Legislativo 4/2015), with effect from
**3 May 2021**, eliminating the obligation to publish quarterly information. The CNMV also issued a
note stating that from that date voluntary quarterly reports could no longer be submitted via the
IPP track and had to be communicated as OIR or, where appropriate, IP.

## Consequence for the corpus

```text
Q1/Q3 <= 2021-05-02
    potentially IPP / required under the former art.120 regime

Q1/Q3 >= 2021-05-03
    NOT_REQUIRED_AS_IPP

voluntary quarterly after that date
    potentially OIR / IP
    OUT_OF_SCOPE_G0
```

The Q1/Q3 slots for 2024–2026 are **not part of the mandatory IPP corpus**. They must not be
labelled `NOT_FOUND`.

## `expected_under_rule` must be temporal

The Circular 3/2018 text still describes Q1/Q3, but the underlying obligation (former art.120) was
removed by a higher-rank norm. Therefore `expected_under_rule` must depend on:

```text
rule + effective_from + effective_to + superior_law + filing_period
```

not on Circular 3/2018 alone. A superior-law change can suppress an obligation that the Circular's
text still describes. This is exactly the kind of temporal problem OpenCNMV should model.

## Evidence

- BOE: Real Decreto Legislativo 4/2015 (LMV text) and Ley 5/2021 (removal of art.120).
- CNMV portal data: Santander has IPP H1/H2 from 2021 onwards, last visible Q3 = 2020; BBVA still
  files Q1-2021 (pre-change) but has no Q1/Q3 IPP in 2024–2026.
