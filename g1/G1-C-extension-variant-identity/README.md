# G1-C — EXTENSION_VARIANT_IDENTITY

**Question.** Can issuer-extension elements (concepts bearing facts, and
dimension members) be paired across the `-es`/`-en` submitted variants using
only structural XBRL evidence — never label translation heuristics?

**Answer.** For the four dual-variant filings, yes for the large majority:
**415 of 449 extension elements** are `PROVEN_EQUIVALENT` under a 1:1
structural rule. The rest are honestly `AMBIGUOUS`, `CONFLICT`, or
`UNMATCHED` — including a natural case where multiple en elements share an
identical structural signature and no pairing is defensible.

## Inputs (committed evidence only)

- `evidence/structure/{variant}.structure.json` — linkbase structure of all
  10 unique variant packages, extracted offline by Arelle 2.44.0
  (`g1c_structure.py`): XBRL properties, ESEF `wider-narrower` anchoring,
  `parentChild` presentation parents, `summationItem` calculation arcs, and
  `dimension-domain` / `domain-member` paths per extension element.
- `../G1-B.../evidence/parse/run1/*.facts.jsonl` — only to know which ext
  elements bear facts / are used as dimension members.
- `../G1-B.../evidence/compare/*` — the G1-B baseline dataset.

## Equivalence rules (preregistered)

Each extension element is evaluated under each role it plays:

| role | signature |
|---|---|
| `FACT_CONCEPT` | type, periodType, balance, substGroup, abstract, nillable **+** wider-narrower anchor set (both directions) **+** presentation parent signatures **+** calculation parents/children with weights |
| `DIMENSION_MEMBER` | per member-path: axes signatures, parent-chain signatures, `usable` |

Referenced extension nodes carry a language-invariant structural signature
(anchor set + XBRL properties). Labels are never read.

Two tiers: signatures **without** sibling order first; if a candidate is
unique it is `PROVEN_EQUIVALENT` (order difference recorded as detail). If
several candidates remain, **ordered** signatures disambiguate — position is
the last available evidence (`order_disambiguated: true`). If still not 1:1:

```text
>1 candidates                    -> AMBIGUOUS
unique anchor match, conflicting
  properties/paths               -> CONFLICT
none                             -> UNMATCHED
```

Verdict totals (es-side elements + en-only):

```text
SAN-FY2024:  PROVEN 96   CONFLICT 2   UNMATCHED 10
SAN-FY2025:  PROVEN 97
BBVA-FY2024: PROVEN 123  AMBIGUOUS 1  UNMATCHED 1
BBVA-FY2025: PROVEN 99   AMBIGUOUS 10 UNMATCHED 10
```

Empirical note: BBVA-FY2025 contains genuinely ambiguous elements — e.g.
`ActivosPorImpuestos` matches both `TaxAssets` and `TangibleAssets` on the
full unordered signature and order does not disambiguate. They stay
`AMBIGUOUS`; the adversarial control (synthetic identical-signature pair)
confirms the matcher can never pair under ambiguity.

## Mapped re-comparison vs G1-B baseline

`g1c_compare_mapped.py` rewrites fact keys with `pair_id` (only for PROVEN
pairs) and re-runs the identical G1-B classification on the same fact bytes:

```text
                          G1-B baseline    G1-C mapped
MATCH_EXACT                    3,549           6,822
MATCH_NUMERIC_EQUIVALENT           1               9
DIVERGENT_SUBMISSION_FACT          1               1
LANGUAGE_SENSITIVE_NOT_COMPARED  683             683
VARIANT_ONLY_FACT              2,453               6
UNMAPPED_VARIANT_FACT          4,239             132
```

- The BBVA `Equity` +98M/−98M `DIVERGENT_SUBMISSION_FACT` is preserved; **no
  new divergences** appeared. Newly-pairable extension facts all turned out
  `MATCH_EXACT` or `MATCH_NUMERIC_EQUIVALENT` (lexical forms like `0.9`/`0.900`,
  or equal values with different `decimals`).
- Remaining `UNMAPPED_VARIANT_FACT` (132) and `VARIANT_ONLY_FACT` (6) are
  honest residue: AMBIGUOUS/CONFLICT/UNMATCHED elements and real
  multiplicity asymmetries (e.g. an `Assets` fact present only in en).

## Files

- `g1c_structure.py` — offline linkbase structure extraction (Arelle 2.44.0)
- `g1c_map.py` — two-tier equivalence matcher → `evidence/mapping/`
- `g1c_compare_mapped.py` — mapped re-comparison → `evidence/compare_mapped/`
- `g1c_verify.py` — determinism + gate checks → `evidence/g1c_results.json`
- `evidence/structure/` — per-variant structure.json (run1 committed)
- `evidence/mapping/` — mapping evidence datasets
- `evidence/compare_mapped/` — mapped comparison records + dataset
- `_runs/` — gitignored deterministic rebuilds

## Verdict

**PASS** — see `evidence/g1c_results.json` (structure determinism,
mapping determinism, mapped-dataset determinism, adversarial ambiguity
control, natural ambiguity present, BBVA divergence preserved, no new
divergences, PROVEN-only rewriting).

## Limits

- PROVEN means *structurally proven 1:1 equivalence under the preregistered
  signature*, not semantic certainty; `order_disambiguated` pairs rely on
  sibling position as the deciding evidence.
- AMBIGUOUS elements are not merged — they remain unmapped in the dataset.
- Only the four dual-variant filings are in scope; IBE contributes no
  cross-variant comparison (single submitted variant, `FALLBACK_TO_ES`).
- Labels were never used; nothing here claims the Spanish and English names
  "mean the same" — only that the DTS structure makes them the same element.
