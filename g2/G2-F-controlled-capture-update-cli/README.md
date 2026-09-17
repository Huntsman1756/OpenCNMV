# G2-F — CONTROLLED_CAPTURE_AND_UPDATE_CLI 

Gate contract. Written before implementation; the executed verdict and
evidence land in `manifest.json` + `g2f_verify_results.json`.

## Objective

Close the last gap between CNMV's live official surfaces and a
materialized `COLUMNAR_DATASET_V1`: a controlled, auditable, fail-closed
capture+update path exposed through the public CLI.

```text
CNMV (live) -> discovery -> download official bytes (preserved)
            -> parse/validate -> CANONICAL_OBSERVATION_V1
            -> classify -> CANONICAL_DELTA_V1 -> preview
            -> atomic apply
```

G2-D proved the update *engine* over prepared observations. G2-F proves
the *public route*: real CNMV state in, updated dataset out — with
preview, base-hash binding, provenance, no partial publish and zero
silent inference.

Explicitly out of scope (later gates):

- dataset bootstrap from empty (G2-G)
- issuer-universe expansion beyond the frozen corpus (G3-A/G3-B)
- scheduling / daily operation / run ledger (G3-C)
- dataset distribution / release (G3-D)
- REST API / UI / MCP

## Architecture

New production code under `src/opencnmv/`:

```text
capture/            the ONLY network-capable production code path
    discover.py     issuer/period filing inventory over official surfaces
                    (wraps source.cnmv.discovery; no reimplementation)
    fetch.py        artifact download + write-once raw preservation +
                    capture manifest (sha256, bytes, media_type,
                    source_url, retrieved_at, http_status)
    assemble.py     captured evidence -> canonical filing objects +
                    CANONICAL_OBSERVATION_V1 (generalized form of the
                    construction g2c_materialize.py did per-fixture:
                    variants, view_resolutions incl. FALLBACK, events
                    with variant scoping, extension_mappings, states)
```

`update/` (G2-D, offline) is consumed unchanged: `classify`, `delta`,
`apply`, `integrity`. The update engine still never fetches.

CLI verbs (thin layer, `opencnmv.cli`):

```text
opencnmv observe --evidence-dir DIR --out FILE
                 [--issuer NIF]... [--family ifa|ipp]...
                 [--from DATE] [--to DATE] [--min-delay S]
                 (live CNMV; writes raw artifacts + capture manifest +
                  CANONICAL_OBSERVATION_V1 document)

opencnmv update --dataset PATH
                (--observation FILE | --evidence-dir DIR [scope flags])
                [--dry-run] [--fail-on-unresolved] [--json]
```

- `update --observation FILE` is fully offline and deterministic — the
  replayable verification path.
- `update` without `--observation` runs capture first (requires
  `--evidence-dir`), writes the observation doc, then proceeds.
- `--dry-run` runs the complete pipeline and prints the delta preview
  (transitions, row-op counts, predicted corpus hash) but publishes
  nothing: zero dataset bytes changed.

## Hard rules (preregistered)

1. **Raw is immutable.** Every downloaded artifact is preserved
   write-once in the evidence dir with sha256 recorded before any
   parsing. A re-fetched artifact whose bytes differ is evidence of a
   changed source, never an overwrite.
2. **Fail closed.** Ambiguous issuer picker, unexpected source shape,
   malformed observation, stale base, integrity failure — each aborts
   before any dataset write, with a deterministic exit code.
3. **No silent inference.** UNRESOLVED transitions are reported, never
   applied; `--fail-on-unresolved` turns them into a non-zero exit and
   no publish.
4. **Atomic publish only.** Apply goes through G2-D's staged write +
   full integrity + rename-swap. A crashed run leaves the prior dataset
   intact; staging is never authoritative.
5. **Network is confined to capture.** `observe` and `update`'s capture
   leg are the only network surfaces; `update --observation` must run
   under socket deny-all. Requests are sequential, single-session, with
   a declared UA and a minimum inter-request delay (default 1.0s).
6. **Partial-scope updates are safe.** Only filings present in the
   observation are eligible for removal claims; unobserved filings
   (e.g. TEF when updating SAN/BBVA/IBE) are never touched.
7. **Frozen scope.** Capture targets the frozen corpus issuers
   (SAN/BBVA/IBE) and families (ifa ESEF, ipp) by default; arbitrary
   issuer expansion is G3 work.
8. **Determinism where it holds.** The delta produced from a fixed
   observation + fixed base is byte-identical across runs and hash
   seeds. Live capture output itself is timestamped (captured_at) but
   the observation *semantic* hash excludes capture metadata.

## Exit codes (extends CLI V1)

```text
0  success (including NO_CHANGE)
1  unexpected internal error
2  usage error / ambiguous scope / invalid flags
3  dataset missing/unreadable
4  canonical object not found
5  dataset integrity failure
6  unsupported operation / missing optional dependency
7  capture/source failure (CNMV unreachable, non-200, unexpected shape,
   issuer-selection ambiguity, retrieval limits exceeded)
```

## Acceptance matrix

Amendments agreed at review (2026-09-17):

* **F2 is conditional on unchanged source state.** If CNMV legitimately
  changes an artifact between capture A and B, that is a real source
  change: distinct semantic hashes, both evidences preserved — not a
  determinism failure.
* **F7's clean-rebuild oracle is rebuilt from the newly captured live
  evidence**, not compared to the G2-C corpus hash. `b261…045f69` is the
  update base, not the required live result.
* **F2/F14 repetition uses representative recapture**, not a second full
  sweep: one dual-language issuer (SAN or BBVA), IBE (fallback), and at
  least one IPP H2 state.

```text
F1  `observe` produces CANONICAL_OBSERVATION_V1 + write-once raw
    evidence + capture manifest from live CNMV for the frozen issuers
F2  observation passes update.observe.validate(); semantic hash
    present and stable across a repeated capture of unchanged source
    (conditional — see amendments)
F3  `update --observation` is fully offline (runs under socket
    deny-all with zero attempts)
F4  `--dry-run`: complete pipeline, delta preview emitted, zero
    dataset bytes changed
F5  second identical update -> NO_CHANGE, zero row ops, dataset
    byte-identical
F6  live end-to-end: observe -> update -> applied dataset passes
    `dataset validate`
F7  incremental apply == clean-rebuild oracle for the observed state
    (G2-D D13 equivalence on the public path)
F8  ambiguous issuer selection / unexpected source shape -> exit 7,
    no dataset write
F9  network failure mid-capture -> dataset untouched; no observation
    presented as authoritative; partial evidence clearly marked
F10 stale base (dataset advanced since delta) -> StaleBaseError,
    fail closed
F11 tampered observation document -> ObservationError, no apply
F12 injected failure inside apply -> no partial publish, prior
    dataset intact
F13 UNRESOLVED transitions reported in preview and result;
    --fail-on-unresolved -> non-zero exit, nothing published
F14 re-capture writes no duplicate artifacts; identical bytes are not
    re-stored; differing bytes kept separately with own sha256
F15 applied provenance rows carry evidence-relative paths, sha256,
    retrieval metadata; no machine-absolute paths
F16 issuer-scoped update leaves unobserved filings untouched (no
    spurious removal claims)
F17 IBE live observation still yields one submitted variant +
    FALLBACK_TO_ES (no phantom #en)
F18 H2/fy semantic separation preserved through the public path
    (CURRENT_HALF contexts remain distinct)
F19 deterministic human + JSON output; diagnostics on stderr
F20 exit-code contract verified incl. code 7
F21 single-session sequential capture; UA declared; min-delay honored
F22 unit + CLI tests; ruff clean; mypy clean; wheel smoke covers the
    new verbs (offline paths)
F23 regressions: G2-A/B/C/D/E verify PASS on final HEAD
F24 docs updated: docs/CLI.md command tree, docs/G2.md, docs/STATUS.md
```

## Inputs

- Live CNMV official surfaces (`busqueda?id=25`, `listaifi`,
  `infadicionifa`, `verdocumento`) — the only authoritative source.
- Pinned G2-C dataset (`dataset/v1`, corpus logical sha
  `b2612152f46406a5…045f69`) as the update base.
- Captured live evidence + observation documents preserved under the
  gate `_out/` (transient) with committed manifests/hashes — same
  pattern as G0-R/G1 (raw bytes preserved; committed evidence is
  metadata, the capture outputs are pinned inputs for replay).

## Results (executed 2026-09-17)

**PASS — 31/31 checks** (`g2f_verify_results.json`).

Live captures (one sequential session each, declared
`OpenCNMV/0.1.0` User-Agent, 2.0 s minimum delay, scoped strictly to
SAN/BBVA/IBE x the frozen periods):

| leg | capture_id | fetches | purpose |
|-----|------------|---------|---------|
| A   | cap-202609172146190000 | 69 | full frozen corpus -> obsA |
| B   | cap-202609172159400000 | 46 | SAN+BBVA recapture (F2) |
| A'  | cap-202609172201420000 | 11 | IBE IPP same-store dedup probe (F14) |

- Observation `obsA` sha256
  `4cf7155d5b600a079f3a23dd814b814a1b21bc02a6fac2ba9bcbd1556802d36e` —
  identical whether written during the live run or re-assembled offline
  from the preserved evidence, and byte-identical to the synthetic
  no-change observation derived from the G2-C dataset itself.
- All 21 filings classified `NO_CHANGE` against base
  `b2612152f46406a5…045f69`; apply is a no-op, dataset bytes unchanged.
- F7 clean-rebuild oracle: bootstrap observation from the same liveA
  evidence -> all-rows delta -> per-filing comparison against the
  incremental result is equal on every table. Documented exclusions:
  per-capture retrieval metadata (`retrieved_at`, `resolved_url`,
  `evidence_path`, `source_url`, `http_status` on `provenance`;
  `source_url` on `artifact`), the curated fixture overlay
  `filing.extras_json`, and the fixture-era `filing` label inside
  extension-mapping `record_json` — none of them semantic content.
- F14: identical XBRL bytes deduplicate (0 new semantic artifacts);
  CNMV detail pages differ per request and are preserved as new
  write-once objects (source change, not a determinism failure).
- IBE live: `en` UI resolves `FALLBACK_TO_ES`, no phantom `#en`
  variant; H2 IPP filings keep their 12-31 `CURRENT_HALF` semantics
  distinct from FY/ESEF.

Wheel smoke: wheel built and installed into a clean venv; 6
`observe`/`update` commands exercised offline (exit codes 0/3/5/7).
Regressions on final HEAD: G2-A 6/6, G2-B 8/8, G2-C 20/20,
G2-D 21/21, G2-E 29/29. Unit suite 81/81, ruff + mypy clean.
