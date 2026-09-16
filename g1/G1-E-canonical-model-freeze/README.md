# G1-E — CANONICAL_MODEL_FREEZE

**Verdict: PASS** (12/12 checks, `g1e_verify.py`)

Not an investigation gate — a model-closure gate. Freezes the canonical
model as a machine-readable schema plus invariants and evidence-built
fixtures. No new CNMV fetches; everything derives from preserved G1
evidence.

## Contents

- `canonical_model.py` — Pydantic schema (entities: `filing`,
  `filing_version`, `submission_variant`, `variant_version`,
  `view_resolution`, `version_event` + `affects`, `extension_mapping`,
  `fact` with structural key vs payload).
- `canonical_model_v1.schema.json` — exported JSON Schema (deterministic).
- `g1e_build_fixtures.py` — rebuilds the four fixtures from frozen G1
  evidence (byte-identical rebuild verified).
- `fixtures/` — `ibe_fy2024`, `bbva_fy2024`, `san_fy2024`, `tef_20484`.
- `docs/CANONICAL_MODEL_V1.md` — the frozen model document, invariants and
  G0→V1 migration.

## The G1-D consequence encoded here

`variant_artifact_set_id` (content hash) was correct as capture-time
identity in G1-B but **cannot** be the stable identity of
`submission_variant` once per-variant replacement is proven (TEF-20484
en-only substitution). V1 separates:

```text
submission_variant.variant_id   = filing#language        (stable)
variant_version.artifact_set_id = content hash           (per version)
```

The TEF fixture encodes it: `#en` has `v1` (unobserved superseded state) →
`v2` (observed, `created_by` the 13/03 event, `source_nreg` null, component
scope `SOURCE_DESCRIBED`); `#es` has a single version; the 28/02 event stays
`VARIANT_SCOPE_NOT_OBSERVABLE` with no inferred `BOTH`.

## Checks (12/12 PASS)

Schema validation of all fixtures; invariants I1–I9 asserted against the
fixtures; TEF temporal shape (en: unobserved→observed, es: single);
fixtures + schema rebuild byte-identical.

## Reproduce

```bash
python g1e_build_fixtures.py   # fixtures + schema, offline
python g1e_verify.py           # 12 checks
```
