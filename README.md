# OpenCNMV

An open, reproducible and auditable layer over official financial information of issuers
published by the **CNMV** (Comisión Nacional del Mercado de Valores).

> **CNMV official-source-first + identity + immutable raw artefacts + revision semantics +
> native XBRL facts + reproducible datasets.**

OpenCNMV is **not** a "Spanish EDGAR" and does not replace CNMV, ESAP, filings.xbrl.org, Arelle or
ESMA `esef_toolkit`. It reuses mature OSS (Arelle, ESMA `esef_toolkit`) behind a thin adapter and
models the CNMV data in a canonical way.

## Status

Currently in **G0-R — CNMV Source & Reproducibility Probe**. The operational status lives in
[`docs/STATUS.md`](docs/STATUS.md); the authority on gates and criteria is
[`AGENTS.md`](AGENTS.md) + [`docs/gates/G0-R.md`](docs/gates/G0-R.md).

## Repository layout

```
AGENTS.md              Permanent rules (source of truth, reuse, raw immutable, gate honesty)
docs/
  PROJECT.md           Mission + conceptual model (filing / filing_version / artifact / fact)
  gates/G0-R.md        The 18 gates, frozen corpus, closure criteria, execution order
  decisions/           Architecture / source-approach ADRs
  findings/            Open findings and discoveries
  STATUS.md            Operational status only (gates, checkpoint, next action)
g0-r/                  G0-R gate evidence + manifests (R00-legal … R04-artifact-url-stability)
```

## Corpus (frozen)

- Issuers: **SAN** (Banco Santander), **BBVA**, **IBE** (Iberdrola)
- ESEF: **FY2024**, **FY2025**
- IPP: **H1-2024, H2-2024, H1-2025, H2-2025, H1-2026**
- Q1/Q3 ≥ 2021-05-03 are **NOT required as IPP** (Ley 5/2021 removed former art.120 LMV)

## License

[MIT](LICENSE)
