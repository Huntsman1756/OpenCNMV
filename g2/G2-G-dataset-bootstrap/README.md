# G2-G — DATASET_BOOTSTRAP (preregistered)

Gate contract. Written before implementation; the executed verdict and
evidence land in `manifest.json` + `g2g_verify_results.json`.

## Objective

Close the last operational gap between "software that can update a
dataset" and "software a user can install and use": reproducible
creation of a `COLUMNAR_DATASET_V1` **from an empty directory**,
without copying any gate `_out/`, frozen fixture, or bespoke builder.

Single question:

> Can a clean OpenCNMV installation create from scratch a valid,
> reproducible `COLUMNAR_DATASET_V1` — usable by the full read-only
> CLI — using only preserved official evidence or a controlled CNMV
> capture, with no prior base dataset and no gate code?

## Architecture

```text
OFFLINE BOOTSTRAP (deterministic oracle)
    CANONICAL_OBSERVATION_V1  --or--  evidence-dir -> assemble
              |
              v
    plan(empty tables, observation) -> all-rows CANONICAL_DELTA_V1
              |
              v
    atomic publish -> dataset/v1 + dataset_manifest.json

LIVE BOOTSTRAP (composition, not a third implementation)
    CNMV -> observe -> evidence-dir -> OFFLINE BOOTSTRAP
```

`init` is a **promotion**, not new machinery: the delta engine already
supports an empty base (`g2f` F7/F12 exercised `plan(empty, obs)` +
`apply_delta`). G2-G exposes it through the public CLI and proves the
result is a first-class dataset, not a degraded bootstrap artifact.

Explicitly out of scope (later gates):

- Universe expansion beyond the frozen corpus (G3-A).
- Overwrite/replace/upgrade of an existing dataset — **V1 offers no
  overwrite option at all**; `init` on a non-empty destination fails.
- Dataset V2 / schema migration machinery.
- Dataset distribution/release packaging (G3-D).

## Hard rules (preregistered)

1. **No base state.** `init` requires an empty (or non-existent)
   destination; it never reads a prior dataset, and it must not be
   used to mutate one. Updates remain `update`'s job.
2. **No gate imports.** Production bootstrap code must not import from
   `g0-r/`, `g1/`, or `g2/` — verified by module scan, same mechanism
   as G2-A A3.
3. **Canonical data only.** The bootstrapped dataset must be valid
   with `filing.extras_json = None`. Curated research annotations
   (`fact_examples`, `extension_mapping_summary`, fixture-era labels
   inside `extension_mapping.record_json`) are gate overlays, not
   canonical content; bootstrap must not require or fabricate them.
4. **Determinism.** Offline bootstrap from the same inputs is
   byte-identical across repeated runs and across hash seeds; live
   evidence -> offline replay produces the identical dataset.
5. **Atomicity.** A mid-bootstrap failure leaves no directory that
   looks like a valid dataset (staging cleaned or manifest absent —
   `dataset validate` must fail on the remnant).
6. **No absolute paths.** Manifest and provenance rows carry
   evidence-relative paths only.
7. **Semantic completeness.** The bootstrapped dataset must preserve
   IPP+ESEF families, dual submitted variants, IBE `FALLBACK_TO_ES`
   (no phantom `#en`), typed dimensions, compound units, fact
   multiplicity, and extension mappings — same bar as G2-C.
8. **Update round-trip.** `opencnmv update` with the same observation
   on the bootstrapped dataset yields `NO_CHANGE` (bootstrap is the
   fixpoint of the update engine).

## CLI (extends CLI V1)

```text
opencnmv init --dataset PATH --observation FILE
opencnmv init --dataset PATH --evidence-dir DIR
opencnmv init --dataset PATH --live [--issuer NIF]... [--family F]...

  --observation FILE   replayable observation document (offline)
  --evidence-dir DIR   assemble an observation from preserved
                       evidence, then bootstrap (offline)
  --live               composition: run `observe` into a fresh
                       evidence dir, then bootstrap from it
                       (the only network path; same session/UA/delay
                       courtesy as observe)
```

- Destination exists and is non-empty -> fail (no overwrite flag in
  V1).
- `--live` is literally `observe` + `init --evidence-dir`; it does not
  bypass the offline path.
- Human summary + `--json` document; diagnostics on stderr.

Exit codes: the frozen vocabulary applies unchanged. A non-empty
destination is a usage error (`2`); capture failures stay `7`;
integrity failures stay `5`.

## Acceptance matrix

```text
B1  init --observation on an empty dir produces a dataset that
    `opencnmv dataset validate` passes completely
B2  init --evidence-dir assembles + bootstraps to the same dataset
B3  two offline bootstraps are byte-identical, including under
    different PYTHONHASHSEED values
B4  no base dataset consulted: empty tables -> all-rows delta ->
    publish (no --base concept in the CLI surface)
B5  zero imports from g0-r/, g1/, g2/ in production code (module scan)
B6  dataset validates and serves with extras_json absent; no curated
    fixture overlay is required or fabricated
B7  liveA-captured evidence -> offline init replay == dataset from the
    same observation document
B8  every G2-E read-only command works on the bootstrapped dataset
    (filings/filing/facts/fact/history/compare/events/mappings/
    provenance/dataset info+validate)
B9  `update` with the same observation on the bootstrapped dataset ->
    NO_CHANGE, zero bytes changed
B10 init onto a non-empty destination fails; no overwrite flag exists
B11 injected mid-bootstrap failure -> no apparently-valid dataset
    (validate fails on remnant; staging cleaned)
B12 manifest + provenance: no absolute/machine paths; corpus logical
    sha256 is deterministic
B13 semantics preserved: 21 filings, IPP+ESEF families, dual variants,
    IBE fallback (no phantom #en), typed dims, compound units, fact
    multiplicity, extension mappings, version events
B14 wheel: installed into a clean venv, init from preserved evidence
    succeeds from an empty cwd with no checkout access
B15 deterministic human + JSON output; exit-code vocabulary intact
B16 unit + CLI tests; ruff clean; mypy clean
B17 regressions: G2-A/B/C/D/E/F verify PASS on final HEAD
B18 docs updated: docs/CLI.md command tree, docs/G2.md, docs/STATUS.md
```

## Inputs

- `CANONICAL_OBSERVATION_V1` documents produced by G2-F `observe`
  (live capture) or assembled offline from preserved evidence dirs.
- Preserved evidence: the G2-F liveA store pattern
  (`artifacts/` + `runs/<capture_id>/manifest.json`) — bootstrap input
  is *evidence*, never a gate `_out/dataset` copy.
- Pinned taxonomy evidence (as G2-F) for Arelle parsing.
- Frozen corpus scope only: SAN/BBVA/IBE x the preregistered periods.
