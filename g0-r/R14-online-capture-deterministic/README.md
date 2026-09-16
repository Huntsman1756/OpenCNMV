# R14 — ONLINE_CAPTURE_DETERMINISTIC

**Gate:** R14 — ONLINE_CAPTURE_DETERMINISTIC
**Status:** `PASS`
**Executed:** 2026-09-16 (UTC)

## Objective

Per `docs/gates/G0-R.md`: with the same observation/source state, the pipeline must
generate semantically identical output; execution timestamps, temporary paths and
non-deterministic logs are excluded from the logical hash.

## Design (adversarial, preregistered)

`hash_scope.json` was committed **before** run A. It fixes what enters the logical
hash (issuer, `source_registration_no`, artifact role, stable `?e=` locator, raw
sha256, byte size, media type, taxonomy selection, full native fact semantics —
QName/context/period/unit/decimals/nil/lang/explicit+typed dims — and revision-event
semantics) and the only exclusions (`retrieved_at`, HTTP Date, `elapsed_ms`, temp
paths, PIDs, log noise, the ephemeral IPP `?t={GUID}`). **`?e=` tokens are in scope**:
R4 declared them stable, so a change must be detected — they were identical.

Two fully isolated runs (`r14_compare.py` orchestrates; `r14_capture.py` is the
single-run pipeline):

```text
RUN A   temp root A   empty Arelle cache (TMP redirect → <root>\local\Arelle)   PYTHONHASHSEED=1
RUN B   temp root B   empty Arelle cache                                       PYTHONHASHSEED=777
```

`PYTHONHASHSEED` is varied deliberately: any output that secretly depends on
dict/set iteration order surfaces as a difference.

Each run performs the real pipeline end to end: `listaifi`/`ListadoIFA` discovery →
IPP `nreg`→detail→fresh `?t={GUID}`→download (final `?e=` recorded) → ESEF
component tokens → 27 raw artefacts → `infadicionifa` event walk → taxonomy
selection from raw bytes (schemaRef → pinned package set) → **offline Arelle parse
reusing the identical R11/R12 harness code** (imported; only the I/O globals are
redirected to the run root) → canonical projections. Multi-MB base64 facts are
compared by `value_sha256`+`value_len`, never inlined.

## Validity precondition

`source_state_A == source_state_B` is required before any pipeline comparison is
meaningful; a difference would mean CNMV state changed between runs (reported as
`INCONCLUSIVE_SOURCE_DRIFT`, not a pipeline fault). **It was equal.**

## Results

```text
source_state_equal             PASS   (same source state across runs)
discovery_logical_hash         A == B
artifact_manifest_logical_hash A == B
taxonomy_logical_hash          A == B
events_logical_hash            A == B
facts_logical_hash             A == B
control_projection             A != B   (negative control — MUST differ)

27/27 artefacts byte-identical across runs (raw sha256 + ?e= locator + size)
ESEF 6/6 parsed identical       IPP 15/15 parsed identical
ioerr=0, Control A (API vs OIM) multiset-equal on 21/21

R14 ONLINE_CAPTURE_DETERMINISTIC = PASS
```

Bonus cross-session evidence: all 21 `facts.jsonl` produced by run A are
**byte-identical** to the committed R11/R12 gate evidence (`facts_equal_to_prior_gates
= 21/21`) — the same semantic inventory is reproduced across sessions, temp roots,
hash seeds and fresh downloads.

The negative control (`artifact manifest + retrieved_at + ?t={GUID}`) **does**
differ between runs — the normalizer is removing real volatility, not
accidentally-constant data.

## Findings

1. The full capture pipeline (discovery → retrieval → taxonomy → parse → fact
   inventory) is deterministic under the preregistered scope: identical canonical
   output on two isolated runs with different temp roots, fresh Arelle caches and
   different `PYTHONHASHSEED`.
2. `?e=` artefact locators re-confirmed stable across independent sessions (in
   scope, unchanged); `?t={GUID}` re-confirmed ephemeral (differs; excluded).
3. Fact inventories hash-identical to R11/R12 evidence — determinism holds across
   sessions, not only within one run pair.
4. Arelle operates correctly with an empty per-user cache redirected via `TMP`
   (Windows `tempfile.gettempdir()` derivation): no cache was needed for the parse —
   a direct R15 precondition check, already satisfied.

## Limitations

- Determinism is proven for the pipeline as exercised on the frozen corpus at this
  source state; it does not claim CNMV responses are byte-stable forever (that is
  what `source_state` drift detection is for).
- The IPP `?t={GUID}` transport locator is volatile by design (R4/R6) and correctly
  excluded; canonical identity remains `nreg`/`registro`.
- `IXBRL_CONSOLIDATED`/`IXBRL_INDIVIDUAL` direct-view tokens are recorded in the
  discovery projection but not re-downloaded (byte-equal package members, R7).

## Evidence

- `hash_scope.json` — preregistered inclusion/exclusion contract
- `r14_capture.py` — single-run pipeline; `r14_compare.py` — A/B orchestrator
- `evidence/run{A,B}/{discovery,artifact_manifest,taxonomy,events,facts_index,
  source_state,control_projection,fetch_log}.json` — canonical projections + the
  volatile fetch log (audit only, not hashed)
- `evidence/r14_results.json` — level-by-level hashes, verdict, cross-gate check
- `_runs/` — full run roots (raws, Arelle parse outputs, isolated caches);
  retained locally, gitignored (canonical projections are the committed evidence)
