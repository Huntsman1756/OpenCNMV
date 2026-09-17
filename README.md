# OpenCNMV

An open, reproducible and auditable layer over official financial information of issuers
published by the **CNMV** (Comisión Nacional del Mercado de Valores).

> **CNMV official-source-first + identity + immutable raw artefacts + revision semantics +
> native XBRL facts + reproducible datasets.**

OpenCNMV is **not** a "Spanish EDGAR" and does not replace CNMV, ESAP, filings.xbrl.org, Arelle or
ESMA `esef_toolkit`. It reuses mature OSS (Arelle, ESMA `esef_toolkit`) behind a thin adapter and
models the CNMV data in a canonical way.

## Status

**G0-R** (source & reproducibility probe) closed with final verdict `GO`; **G1**
(canonical model design) frozen at tag `g1-model-frozen`; **G2** (durable core
implementation) in progress. The operational status lives in
[`docs/STATUS.md`](docs/STATUS.md); the authority on gates and criteria is
[`AGENTS.md`](AGENTS.md) + [`docs/gates/G0-R.md`](docs/gates/G0-R.md).

## Repository layout

```
AGENTS.md              Permanent rules (source of truth, reuse, raw immutable, gate honesty)
docs/
  PROJECT.md           Mission + conceptual model (filing / filing_version / artifact / fact)
  CANONICAL_MODEL_V1.md Frozen canonical model spec (tag g1-model-frozen)
  gates/G0-R.md        The 18 gates, frozen corpus, closure criteria, execution order
  decisions/           Architecture / source-approach ADRs
  findings/            Open findings and discoveries
  STATUS.md            Operational status only (gates, checkpoint, next action)
src/opencnmv/          Durable core library (model / source.cnmv / xbrl /
                       canonicalize / provenance / serialize)
tests/                 Regression tests (unittest; see CONTRIBUTING.md)
g0-r/                  G0-R gate evidence + manifests (R00 … R17)
g1/                    G1 design-gate evidence + manifests (G1-A … G1-E)
g2/                    G2 build-gate evidence + manifests (G2-A, G2-B)
```

## Development

Install, test, lint, type-check and build instructions live in
[`CONTRIBUTING.md`](CONTRIBUTING.md). CI runs the same checks on Linux and
Windows under Python 3.11.

## Corpus (frozen)

- Issuers: **SAN** (Banco Santander), **BBVA**, **IBE** (Iberdrola)
- ESEF: **FY2024**, **FY2025**
- IPP: **H1-2024, H2-2024, H1-2025, H2-2025, H1-2026**
- Q1/Q3 ≥ 2021-05-03 are **NOT required as IPP** (Ley 5/2021 removed former art.120 LMV)

## License

[MIT](LICENSE)
