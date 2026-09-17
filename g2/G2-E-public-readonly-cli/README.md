# G2-E — PUBLIC_READ_ONLY_CLI

Gate contract. **Preregistered before implementation** — the command tree,
exit codes, and check matrix below are the acceptance criterion; code is then
written to satisfy it.

## Question

Can an external user inspect a materialized `COLUMNAR_DATASET_V1` through a
stable, deterministic, read-only CLI that exposes the proven canonical
semantics — variants, versions, events, facts, dimensions, mappings,
provenance — without collapsing them, without mutating the dataset, and
without any network access?

## Production code under test

```
src/opencnmv/
  query/
      dataset.py      resolve + open + manifest verification gate
      filings.py      discovery filters + canonical filing detail
      facts.py        bounded fact queries + full fact detail
      history.py      variant/version lifecycle + events
      compare.py      G1-B/G1-C cross-variant semantics (promoted)
      mappings.py     extension_mapping surface
      events.py       version_event surface
      provenance.py   row -> source evidence trace
  cli/
      errors.py       exit-code vocabulary + CliError
      formatting.py   deterministic human tables / JSON / JSONL
      main.py         argparse tree + dispatch (thin only)
src/opencnmv/__main__.py      python -m opencnmv
pyproject [project.scripts]   opencnmv = opencnmv.cli.main:entry
```

The CLI is a thin presentation layer: all semantics live in
`opencnmv.query` over the existing `opencnmv.dataset` surface
(Parquet + manifest authoritative; DuckDB read-only query engine).
`opencnmv.xbrl` / Arelle are never imported by the CLI path.

## Frozen CLI V1 contract

### Dataset resolution (precedence)

```
1. --dataset PATH            (per-command or global, flag wins)
2. OPENCNMV_DATASET env var
3. ./dataset/v1              (cwd default, only if it exists)
```

No directory scanning. Missing dir / missing or unparseable manifest ->
exit 3. Manifest file-hash/row/schema verification runs before any data
is served; violations -> exit 5. `dataset validate` additionally
recomputes every table's logical sha256 + corpus hash + referential and
update invariants.

### Command tree

```
opencnmv --version
opencnmv dataset info|validate
opencnmv filings [--issuer S] [--nif S] [--lei S] [--family S]
                 [--period D] [--from D] [--to D]
opencnmv filing <REF>            REF = filing_id | registro_oficial
opencnmv history <REF>           REF = filing_id | registro | variant_id
opencnmv facts [--filing R] [--variant V|lang] [--state S]
               [--concept SUB] [--period D] [--lang L] [--dims SUB]
               [--unit SUB] [--nil] [--limit N] [--count]
opencnmv fact <FACT_ID>
opencnmv compare <FILING_REF> [--class C] [--limit N]
opencnmv events [FILING_REF]
opencnmv mappings <FILING_REF> [--verdict V]
opencnmv provenance (--fact ID | --artifact ID | --state ID)
```

Output flags: `--json` (single document) everywhere; `--jsonl` (one object
per line) on list commands (`filings`, `facts`, `events`, `mappings`).
`facts` default `--limit` is 100; `--limit 0` disables. Machine output:
stdout = data only, stderr = diagnostics, no ANSI, canonical IDs verbatim,
explicit null preserved, `sort_keys` for JSONL.

### Exit codes (frozen)

```
0  success
1  unexpected internal error (never a bare traceback)
2  usage error (bad args, ambiguous identifier, invalid filter value)
3  dataset missing / unreadable (no dir, no manifest, unparseable)
4  canonical object not found
5  dataset integrity failure (manifest hash/row/schema violation,
   required file missing, referential/logical-hash check failed)
6  unsupported operation / optional dependency unavailable
     (duckdb / pyarrow not installed)
```

Unhandled exceptions are never user-facing tracebacks; `--debug` re-raises.

### Read-only guarantee

Every command is read-only: no Parquet/manifest writes, no deltas, no
variant creation, no CNMV contact, no hidden state in the dataset. Gate
proof: sha256 of every authoritative dataset file identical before/after
the full command corpus; all commands execute under socket deny-all.

### Compare semantics (G1-B/G1-C promoted, verbatim rules)

`cross_variant_key` = concept | entity | period | unit | dims (lang
dropped). PROVEN_EQUIVALENT pairs rewrite concept / dim axis / E:member to
`pair_id`; AMBIGUOUS/CONFLICT/UNMATCHED never merge. Multiset pairing per
key (sorted by value_sha256, zip; residue -> VARIANT_ONLY_FACT).
Language-sensitive types (`stringItemType`, `normalizedStringItemType`,
`tokenItemType`, `langItemType`, `textBlockItemType`) ->
`LANGUAGE_SENSITIVE_NOT_COMPARED`, never a divergence. Payload:
identical value_sha256 + decimals -> `MATCH_EXACT`; numeric-equal ->
`MATCH_NUMERIC_EQUIVALENT`; else `DIVERGENT_SUBMISSION_FACT`. Extension
facts that stay unmapped -> `UNMAPPED_VARIANT_FACT`. The public divergence
surface is this classification — never the raw payload-mismatch count.

## Acceptance matrix (preregistered)

| id  | check |
|-----|-------|
| E1  | installed wheel exposes `opencnmv` console entry point |
| E2  | `--help` / command tree matches the frozen contract |
| E3  | `dataset info` matches the pinned G2-C manifest (hashes, counts) |
| E4  | `dataset validate` passes the pinned dataset |
| E5  | `filings` + filters deterministic (golden + assertion) |
| E6  | `filing` detail preserves the full canonical graph |
| E7  | IBE: one submitted variant; UI `en` shows FALLBACK_TO_ES, no `#en` |
| E8  | TEF 20484: `#es` 1 version, `#en` v1->v2, 13/03 EN_ONLY scoped to `#en`, 28/02 NOT_OBSERVABLE |
| E9  | `facts` preserves structural identity + multiplicity (multiset visible) |
| E10 | typed dimension round-trips in machine output |
| E11 | denominator-bearing unit preserved completely |
| E12 | `compare cnmv:ifa:20448` reports the Equity +98M/-98M DIVERGENT fact |
| E13 | language-sensitive text never reported as divergence |
| E14 | non-PROVEN mappings never rewrite identity (verdicts visible) |
| E15 | `provenance` reaches pinned evidence (artifact sha256 + evidence_path) |
| E16 | JSON/JSONL byte-deterministic across runs and hash seeds |
| E17 | exit codes behave exactly per contract (0/2/3/4/5/6 exercised) |
| E18 | corrupt Parquet byte and deleted table both fail closed |
| E19 | full command corpus modifies zero dataset bytes |
| E20 | entire CLI corpus runs under socket deny-all, 0 connect attempts |
| E21 | wheel smoke passes on Windows (this machine) |
| E22 | wheel smoke wired into CI matrix (Linux + Windows) |
| E23 | G2-A regression PASS |
| E24 | G2-B regression PASS |
| E25 | G2-C regression PASS |
| E26 | G2-D regression PASS |
| E27 | dataset-driven compare reproduces G1-C mapped class counts exactly (4 dual filings) |
| E28 | IPP H2: CURRENT_HALF vs YTD contexts sharing period_end stay separate |
| E29 | committed golden outputs reproduce the run byte-for-byte |

## Gate directory

```
g2e_inputs.json           pinned G2-C dataset files (sha256 + logical hash)
g2e_common.py             shared helpers (run CLI in-process, hashing)
g2e_build.py              pin-verify inputs, build minids A/B determinism
g2e_run.py                command corpus under deny-all -> _out/run{A,B}
g2e_wheel.py              build wheel -> clean venv -> smoke commands
g2e_verify.py             E1-E28 evaluation -> g2e_verify_results.json
golden/                   committed deterministic stdout captures
_out/                     gitignored run artifacts
```

The pinned G2-C dataset is used read-only in place (never copied into the
gate; corruption scenarios operate on temp copies).

## Result

**PASS — 29/29.** `g2e_verify_results.json` holds the per-check verdicts;
`manifest.json` records pins, hashes and limitations. Headline evidence:
the pinned corpus hash is served only after manifest verification;
`compare` reproduces the G1-C mapped class counts on all four dual
filings (BBVA-FY2024 `Equity` +98M/−98M is the single
`DIVERGENT_SUBMISSION_FACT`); IBE exposes one submitted variant with the
EN UI fallback recorded, never a phantom `#en`; TEF 20484 shows
`#es` v1 and `#en` v1→v2 with the 13/03 event scoped to `#en` and the
28/02 event `VARIANT_SCOPE_NOT_OBSERVABLE`; the full 48-command corpus
ran twice under socket deny-all with byte-identical output and zero
dataset bytes changed; a corrupt byte or a deleted table fails closed
with exit 5 and empty stdout; the installed wheel passes the same smoke
on Windows locally and Linux+Windows in CI.
