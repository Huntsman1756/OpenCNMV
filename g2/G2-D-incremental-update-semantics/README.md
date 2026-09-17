# G2-D — INCREMENTAL_CAPTURE / UPDATE_SEMANTICS

Gate contract. **Preregistered before execution** — the check matrix below is
the acceptance criterion; code was then written to satisfy it.

## Question

Given dataset state S0 and a later authoritative observation O1, can OpenCNMV
deterministically derive S1 — preserving all history and creating only the
canonical rows the observed change requires — without rebuilding or corrupting
historical state and without violating Canonical Model V1?

## Production code under test

```
src/opencnmv/update/
    __init__.py
    transitions.py   closed transition vocabulary
    observe.py       CANONICAL_OBSERVATION_V1 document contract + hashing
    classify.py      (S0 rows, O1) -> semantic transitions + row ops (pure)
    delta.py         CANONICAL_DELTA_V1 document (self-hashed, base-bound)
    apply.py         stale-base check -> merge -> integrity -> staged publish
    integrity.py     update invariants (supersedes chains, event scope, ...)
```

The update path is a genuine canonical delta: rows are computed by
`classify`/`delta`, applied by `apply` via staging + rename publish. A clean
full rebuild is used **only as a verification oracle**, never as the update
mechanism.

## Transition vocabulary (closed set — `update/transitions.py`)

`NO_CHANGE`, `NEW_FILING`, `NEW_FILING_VERSION`, `NEW_SUBMISSION_VARIANT`,
`NEW_VARIANT_VERSION`, `NEW_VERSION_EVENT`, `VARIANT_SCOPED_VERSION_EVENT`,
`FILING_SCOPE_NOT_OBSERVABLE`, `ARTIFACT_CHANGED`, `ARTIFACT_ADDED`,
`ARTIFACT_REMOVED`, `FACT_ADDED`, `FACT_REMOVED`, `FACT_PAYLOAD_CHANGED`,
`EXTENSION_MAPPING_ADDED`, `EXTENSION_MAPPING_CHANGED`,
`VIEW_RESOLUTION_RECORDED`, `SOURCE_STATE_CONFLICT`, `UNRESOLVED`.

Row-operation policy (Canonical Model V1 is an evidence ledger):

* Canonical rows are **append-only**. Superseded versions' artifacts/facts are
  historical capture records and are never deleted. `ARTIFACT_REMOVED` /
  `FACT_REMOVED` are semantic transitions describing the newer version's set —
  not row deletions.
* Exactly two metadata surfaces may update in place, always recorded in the
  delta with before/after: `variant_version.created_by_event_id` backfill
  (None -> event) and `extension_mapping` analysis fields (PROVEN-only
  `rewrites_identity` is recomputed by the engine, never trusted from input).
* Any other content difference under an existing identity is
  `SOURCE_STATE_CONFLICT` — never silently applied.
* `rows_removed` is reserved and always empty.

## Observation contract (`CANONICAL_OBSERVATION_V1`)

An observation is the canonical projection of one authoritative capture —
the complete canonical filing object (including still-valid history), plus
fact states for variant_versions the observation introduces, mapping record
files, event-owned artifacts, and optional `artifact_dispositions` removal
evidence. Capture produces it; classify/apply consume it fully offline.

* `observation_sha256` hashes the filings payload only — re-capturing
  identical source state under a new `observation_id`/`captured_at` replays
  identically.
* `states` carry facts only for new variant_versions; identical resubmission
  of a recorded state is an idempotent replay (NO_CHANGE), differing bytes
  under a recorded `state_id` are `SOURCE_STATE_CONFLICT`.
* Rows present in the dataset but absent from the observation are removal
  claims: justified only by `artifact_dispositions.REMOVED_CONFIRMED`
  (emits `ARTIFACT_REMOVED`, row retained) — otherwise `UNRESOLVED`.

## Delta document (`CANONICAL_DELTA_V1`)

`{delta_format, delta_id (self-hash), base_corpus_logical_sha256,
observation_id, observation_sha256, transitions, unresolved, rows_added,
rows_updated, rows_removed, result_corpus_logical_sha256, stats}`

* `delta_id` = sha256 over the canonical delta payload — tamper-evident.
* `base_corpus_logical_sha256` binds the delta to one exact base; applying to
  any other base raises `StaleBaseError`.
* `result_corpus_logical_sha256` is the predicted S1 hash; the staged dataset
  must reproduce it before publish.

## Apply semantics (`update/apply.py`)

1. base hash must equal `delta.base_corpus_logical_sha256` — else stale.
2. delta self-hash + row-shape verification.
3. pure in-memory merge with `before`-image and PK-duplicate checks.
4. full dataset integrity + update invariants on merged state **before** any
   write.
5. complete S1 written to `<name>.staging-<delta>`; manifest built and
   verified; predicted result hash enforced.
6. publish by rename swap (`v1` -> `.prev`, `staging` -> `v1`, drop prev).
   A crash before the final rename leaves the original dataset authoritative;
   staging is never authoritative.

## Scenario construction

All evidence derives from the pinned G2-C runA dataset
(`g2d_inputs.json` pins every file's sha256):

* **Decompile**: dataset rows -> `CANONICAL_OBSERVATION_V1` filing entries
  (`filing_from_rows`, `record_from_row`, `record_json`, extras overlay).
  The decompile is itself a round-trip check.
* **Carve**: S0 = the corpus minus a scenario's subgraph (rows physically
  removed, then re-materialized as a standalone dataset).
* **Oracle**: corpus-restoring scenarios must reproduce the pinned G2-C
  dataset **byte-identically**; synthetic-state scenarios use an independent
  observation-union materializer (`g2d_common.oracle_materialize`) as the
  clean-rebuild reference.

Scenarios (full definitions in `g2d_scenarios.json`):

| id | title | oracle |
|----|-------|--------|
| A  | NO_CHANGE (replay incl. identical state resubmission) | g2c_runA |
| B  | NEW_FILING (IBE H1-2026) | g2c_runA |
| C1 | UI fallback replay creates no variant | g2c_runA |
| C2 | new UI-language resolution records row, no variant | built |
| D  | new real `#en` variant (BBVA FY2024) | g2c_runA |
| E  | TEF 20484 13/03 EN_ONLY_REPLACED -> `#en#v2` | g2c_runA |
| F  | TEF 20484 28/02 VARIANT_SCOPE_NOT_OBSERVABLE | g2c_runA |
| G  | changed fact payload, same structural identity | built |
| H1 | artifact absent, no evidence -> UNRESOLVED | self |
| H2 | artifact REMOVED_CONFIRMED -> annotation, row kept | self |
| I1 | extension mappings added | g2c_runA |
| I2 | mapping evolution (promote/demote/adversarial) | built |
| I3 | mapping file shrinks -> UNRESOLVED | self |

## Acceptance matrix (preregistered)

| id  | check |
|-----|-------|
| D1  | NO_CHANGE is byte/logically idempotent |
| D2  | NEW_FILING creates only the required graph |
| D3  | UI fallback creates no phantom variant |
| D4  | new real language variant -> stable variant + v1 |
| D5  | EN_ONLY replacement creates only new EN variant_version |
| D6  | unknown event scope creates no invented variant transition |
| D7  | changed fact payload preserves old + new histories |
| D8  | extension mappings obey PROVEN-only rewrite rule |
| D9  | delta deterministic across hash seeds (17 vs 991) |
| D10 | replay of same observation is idempotent on every scenario |
| D11 | stale-base delta rejected (`StaleBaseError`) |
| D12 | injected mid-update failure leaves prior dataset valid |
| D13 | incremental S1 == clean rebuild S1 (byte-identical where format permits) |
| D14 | referential integrity valid after every scenario, both seeds |
| D15 | manifests + delta self-hash detect tampering |
| D16 | classify/apply run under socket deny-all |
| D17 | zero gate-code imports in production modules |
| D18 | G2-A regression PASS on this HEAD |
| D19 | G2-B regression PASS on this HEAD |
| D20 | G2-C regression PASS on this HEAD |
| D21 | adversarial: absent-artifact and shrunk-mapping observations classify UNRESOLVED; confirmed removal is a row-retaining annotation |

## Adversarial controls covered

* same bytes under `lang=en` -> no EN variant (C1/D3)
* same variant/content replay -> no `#v2` (A, D10)
* new artifact set under EN does not mutate ES (D5 `es_untouched`)
* language-silent event not promoted to scoped (F/D6)
* changed `value_sha256` keeps structural identity (G/D7)
* ambiguous mapping stays ambiguous even when the raw record claims
  `rewrites_identity` (I2/D8)
* stale delta application fails (D11)
* corrupted observation hash fails before update (controls)
* partial write never becomes authoritative (D12, 3 injection points)
* duplicate event replay does not duplicate `version_event` (E replay, D10)

## Execution

```
python g2d_build.py                          # pin-verify + decompile + carve + oracles
PYTHONHASHSEED=17  python g2d_run.py --seed 17  --tag A   # deny-all runs
PYTHONHASHSEED=991 python g2d_run.py --seed 991 --tag B
python g2d_verify.py                          # D1-D21 -> results + manifest
```

Generated `_out/` is gitignored. Committed: `README.md`, `g2d_inputs.json`,
`g2d_scenarios.json`, `g2d_*.py`, `g2d_verify_results.json`, `manifest.json`,
`evidence/`.

## Result

_See `g2d_verify_results.json` + `manifest.json` for the executed verdict._
