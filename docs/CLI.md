# OpenCNMV CLI — `opencnmv` (read-only, v1)

A deterministic, read-only command-line interface over a materialized
`COLUMNAR_DATASET_V1` directory. It exposes the canonical semantics
frozen by G1/G2 — filings, submission variants, variant versions,
lifecycle events, facts with native XBRL identity, extension mappings and
provenance — without collapsing them, without mutating the dataset, and
without any network access.

This document is the frozen CLI V1 contract. `docs/STATUS.md` records
which gate proved it.

## Installation

```bash
pip install "opencnmv[dataset]"        # from the built wheel
# or, from a source checkout:
pip install -e ".[dataset]"
```

The `dataset` extra provides `duckdb` + `pyarrow` (the query engine and
the Parquet reader). Without it every command exits `6` with a clear
message. Arelle / `xbrl` extras are **not** needed and are never imported
by the CLI path.

## The dataset

The CLI reads exactly one thing: a dataset directory produced by the
G2-C materializer, containing `dataset_manifest.json`, one
`<table>.parquet` per canonical table, and `schema/<table>.schema.json`
exports. The reference corpus used by the gates is
`g2/G2-C-columnar-dataset-v1/_out/runA/dataset/v1`
(corpus logical sha256
`b2612152f46406a5ec4858592656c10b0afa8f98b042dc93337782b202045f69`).

### Dataset path resolution (precedence, first hit wins)

```text
1. --dataset PATH            accepted both globally and per-command
2. OPENCNMV_DATASET          environment variable
3. ./dataset/v1              cwd default, only if it exists
```

No directory scanning is performed. A missing directory, a missing or
unparseable manifest, or a manifest that is not `COLUMNAR_DATASET`
produces exit `3`.

### Fail-closed integrity gate

`open_dataset` verifies the manifest **before any data is served**:
per-file SHA-256, row counts, and on-disk Arrow schemas vs the pinned
`COLUMNAR_DATASET_V1` schemas. Any violation exits `5`. `dataset
validate` additionally recomputes every table's logical sha256, the
corpus logical hash, referential integrity and the update invariants
(supersession chains, no silent replacement, scoped events).

## Command tree

```text
opencnmv --version
opencnmv dataset info                     manifest-backed summary
opencnmv dataset validate                 deep integrity validation
opencnmv filings [--issuer S] [--nif S] [--lei S] [--family S]
                 [--period D] [--from D] [--to D]
opencnmv filing <REF>                     full canonical filing graph
opencnmv history <REF>                    variant/version lifecycle + events
opencnmv facts [--filing R] [--variant V] [--state S] [--concept SUB]
               [--period D] [--lang L] [--dims SUB] [--unit SUB]
               [--nil] [--limit N] [--count]
opencnmv fact <FACT_ID>                   one fact: record + dims + provenance
opencnmv compare <FILING_REF> [--class C] [--limit N]
opencnmv events [FILING_REF]
opencnmv mappings <FILING_REF> [--verdict V]
opencnmv provenance (--fact ID | --artifact ID | --state ID)
```

`REF` accepts the canonical `filing_id` (`cnmv:ifa:<nreg>` /
`cnmv:ipp:<nreg>`) or the exact `registro_oficial`. `history` also
accepts a `variant_id` (`<filing_id>#<lang>`). Identifiers are never
fuzzy-matched; an ambiguous `registro_oficial` exits `2`, a missing
object exits `4`.

### Output modes

Every command defaults to a deterministic human-readable table. Machine
output:

* `--json` — one deterministic JSON document (`sort_keys`, `indent=1`,
  `ensure_ascii=False`). Available on all commands.
* `--jsonl` — one JSON object per line; on `filings`, `facts`, `events`,
  `mappings`.

stdout carries data only; diagnostics and errors go to stderr. No ANSI,
no localized number/date formatting, canonical IDs verbatim, explicit
`null` preserved.

`facts` defaults to `--limit 100`; `--limit 0` disables the cap.
`--count` prints only the matching row count. Ordering is always
`(state_id, seq)` — the canonical order — so truncated output is stable
across runs.

## What each command exposes

### `dataset info`

Dataset/canonical-model versions, corpus logical sha256, schema
fingerprint, code commit, generator, per-table row counts + file and
logical sha256, pinned inputs, findings and limitations.

### `dataset validate`

`PASS`/`FAIL` over: required files, manifest file-hashes + row counts +
on-disk schemas, exported schema fingerprints, Parquet readability,
per-table logical hashes, corpus logical hash, referential integrity and
update invariants. Exit `0` on PASS, `5` on FAIL.

### `filings`

Deterministic list (`ORDER BY filing_id`) with issuer denomination, NIF,
LEI, registro_oficial, family, normalized ISO `period_end`, and
variant/version/fact counts. Filters are exact (`--nif`, `--lei`,
`--family`, `--period`) or case-insensitive substring (`--issuer`); date
bounds accept `yyyy-mm-dd` or `dd/mm/yyyy`.

### `filing <REF>`

The complete canonical filing object — filing identity, filing versions
with their artifacts, submission variants with all variant versions
(including unobserved superseded ones), view resolutions, version events
with scoped `affects`, extension mappings, plus a per-state provenance
summary. Nothing is flattened.

### `history <REF>`

Per-variant version chains (`v1 -> v2`, `observed` flags, supersession
links, artifact/fact counts), view resolutions, and version events with
their `scope_status` and `affects` rows. This is the surface that makes
e.g. TELEFÓNICA `cnmv:ifa:20484` legible: `#es` has one version, `#en`
has `v1` (unobserved) superseded by `v2` created by the 2025-03-13
`EN_ONLY_REPLACED` event affecting only `#en`, while the 2025-02-28
event stays `VARIANT_SCOPE_NOT_OBSERVABLE` and asserts no variant.

### `facts` / `fact`

Fact identity is structural — concept, entity, period, dimensions
(explicit **and** typed), complete unit (numerator/denominator
measures), xml:lang — plus `variant_version_id`; payload is separate.
Duplicate facts under a structural key are never collapsed: they appear
as distinct rows with `#<occ>`-suffixed `fact_id`s, and
`fact <id>` reports `structural_key_multiplicity`. `--json` output
includes the lossless `canonical_record` (the facts.jsonl object the row
was materialized from).

### `compare <FILING_REF>`

Semantic cross-variant comparison over the latest *observed* variant
version of each submission variant — the G1-B/G1-C rules, not a raw
payload diff:

* `cross_variant_key` = concept | entity | period | unit | dims
  (`xml:lang` dropped).
* Only `PROVEN_EQUIVALENT` extension mappings rewrite concept / dim-axis
  / explicit-member qnames to `pair_id`. `AMBIGUOUS`, `CONFLICT`,
  `UNMATCHED` never merge.
* Multiset pairing per key, sorted by `value_sha256`, zipped; residue is
  `VARIANT_ONLY_FACT`. Never a cross-product, never a dedup.
* Language-sensitive concept types (`stringItemType`,
  `normalizedStringItemType`, `tokenItemType`, `langItemType`,
  `textBlockItemType`) are `LANGUAGE_SENSITIVE_NOT_COMPARED` — never an
  economic divergence.
* Payload: identical `value_sha256` + `decimals` → `MATCH_EXACT`;
  `Decimal`-equal numerics (`0.9` vs `0.900`) →
  `MATCH_NUMERIC_EQUIVALENT`; otherwise `DIVERGENT_SUBMISSION_FACT`.
* Extension-namespace facts that stay unmapped → `UNMAPPED_VARIANT_FACT`.

Single-variant filings report `SKIPPED_SINGLE_VARIANT` with the
view-resolution evidence — a UI-language fallback (e.g. IBE `en` → `#es`
`FALLBACK_TO_ES`) is not a submitted variant.

`--class C` filters records to one comparison class; `--limit N` bounds
the record list (the counts always cover the full comparison).

### `events [FILING_REF]`

Version events with `event_type`, `event_date`, nullable `source_nreg`,
`scope_status`, and scoped `affects` rows (variant, component scope,
before/after variant versions, scope basis). `source_label` is verbatim
CNMV evidence text — evidence, not classification.

### `mappings <FILING_REF> [--verdict V]`

Every `extension_mapping` row with its verdict and `rewrites_identity`
(`true` exactly when `verdict == PROVEN_EQUIVALENT`). No flag promotes
ambiguous mappings.

### `provenance`

* `--fact ID` — structural identity + every provenance link for the
  fact's state: role, variant_version context, source artifact sha256,
  byte size, media type, source/resolved URL, retrieval metadata, pinned
  repo-relative `evidence_path`, Arelle version.
* `--artifact ID` — `sha256:<hex>` (bare hex accepted): artifact rows and
  every canonical state that consumed it.
* `--state ID` — all provenance links for one frozen corpus state.

Evidence paths are repo-relative pinned locators; the CLI never emits
machine-specific absolute paths.

## Exit codes (frozen)

```text
0  success
1  unexpected internal error (never a bare traceback)
2  usage error (bad args, ambiguous identifier, invalid filter value)
3  dataset missing / unreadable
4  canonical object not found
5  dataset integrity failure
6  unsupported operation / optional dependency unavailable
```

Unhandled tracebacks are never user-facing; `--debug` re-raises.

## Guarantees

* **Read-only.** No command writes to the dataset, its manifest, or any
  source evidence. Gate proof: sha256 of every authoritative dataset
  file is identical before and after the full command corpus.
* **No network.** No command performs network I/O; the whole acceptance
  corpus runs under socket deny-all. The CLI never imports Arelle.
* **Deterministic.** Stable row ordering, canonical JSON, no timestamps
  or machine-local paths in output.
* **Fail-closed.** A corrupted dataset is never presented as valid.

## Limitations (CLI V1)

* Read-only by design: no `fetch`/`update`/`sync`/`apply-delta` — those
  are separate later gates over `opencnmv.update`.
* `compare` pairs the two first submission variants (the corpus's dual
  es/en filings); a corpus with >2 variants per filing is out of scope
  for V1.
* `facts` list rows show `value_preview`; use `fact <id> --json` for the
  lossless `value_full`/`xValue_full` and the canonical record.
* No pagination cursor: `--limit`/`--count` provide bounded, stable
  windows over a deterministic order.
* The CLI does not recompute taxonomy-level semantics; it reports what
  the materialized dataset recorded.
