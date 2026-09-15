# R10 — TAXONOMY_PINNING

**Gate:** R10 — TAXONOMY_PINNING
**Status:** `PASS`
**Executed:** 2026-09-15 (UTC) — after checkpoint `CONTINUE`

## Objective

Freeze every dependency needed to reconstruct/parse the corpus offline. Produce
`taxonomy_manifest.json` with `package`, `source_url`, `retrieved_at`, `sha256`,
`taxonomy_version`, `filing_family`, `required_by`. Pin the exact Arelle version and relevant
configuration.

## Method

`pin_taxonomies.ps1`:

- Reuses the already-preserved CNMV IPP package bytes from R4 (`ipp_2019-01-01_run1.zip`,
  byte-stable run1==run2) and records the pin.
- Downloads the two ESMA ESEF taxonomy packages referenced by the corpus filings and the eight
  `xbrl.org` base schema files imported by the CNMV IPP taxonomy and the ESMA/issuer extensions.
- For each package: raw bytes preserved unmodified, SHA-256 recorded, and a **content check**
  verifies the ZIP actually contains the expected `taxonomy/<date>/esef_cor.xsd` (ESMA) /
  `ipp_{en,ge}_2019-01-01.xsd` (CNMV) entry points.
- Issuer extension taxonomies are **not** downloaded separately: they are members of the
  preserved `ESEF_PACKAGE_ZIP_XBRL` artefacts; the manifest records the member path + SHA-256 of
  the extension `.xsd` and the identifier URL (resolved via `META-INF/catalog.xml`).

## Pinned dependencies (`taxonomy_manifest.json`, 20 rows)

| Package | taxonomy_version | required_by | Source |
|---|---|---|---|
| `cnmv-ipp-2019-01-01` | 2019-01-01 | IPP corpus (ipp_en SAN/BBVA, ipp_ge IBE) | cnmv.es |
| `esma-esef-2022` (v1.1) | 2022-03-24 | ESEF FY2024 filings | esma.europa.eu |
| `esma-esef-2024` | 2024-03-27 | ESEF FY2025 filings | esma.europa.eu |
| `ifrs-full_ifrs-2022-03-24` | 2022-03-24 | ESEF FY2024 (`esef_cor` imports IFRS) | xbrl.ifrs.org canonical files |
| `ifrs-full_ifrs-2024-03-27` | 2024-03-27 | ESEF FY2025 (`esef_cor` imports IFRS) | xbrl.ifrs.org canonical files |
| `xbrl-lei-2020-07-02` | 2020-07-02 | ESEF all (`esef_cor` imports `lei-required.xsd`) | xbrl.org canonical files |
| `xbrl.org:2003/xbrl-instance-2003-12-31.xsd` | 2003 | all | xbrl.org |
| `xbrl.org:2003/xbrl-linkbase-2003-12-31.xsd` | 2003 | ESEF extensions | xbrl.org |
| `xbrl.org:2005/xbrldt-2005.xsd` | 2005 | all | xbrl.org |
| `xbrl.org:2006/xbrldi-2006.xsd` | 2006 | IPP instances | xbrl.org |
| `xbrl.org:dtr/type/2020-01-21/types.xsd` | 2020-01-21 | ESEF FY2024 | xbrl.org |
| `xbrl.org:dtr/type/2022-03-31/types.xsd` | 2022-03-31 | ESEF FY2025 | xbrl.org |
| `xbrl.org:dtr/type/numeric-2009-12-16.xsd` | 2009-12-16 | IPP | xbrl.org |
| `xbrl.org:dtr/type/nonNumeric-2009-12-16.xsd` | 2009-12-16 | IPP | xbrl.org |
| `issuer-extension-{SAN,BBVA,IBE}-{FY2024,FY2025}` (×6) | 20241231 / 20251231 | each ESEF filing | member of preserved package |

## Findings

- **ESEF taxonomy version split confirmed by observation:** FY2024 filings import
  `esef_cor` **2022-03-24** + DTR `2020-01-21`; FY2025 filings import `esef_cor` **2024-03-27** +
  DTR `2022-03-31`. Both ESMA packages verified to contain the expected dated entry point.
- **Issuer extension domain change is real:** SAN's extension moved from `santanderbank.com`
  (FY2024) to `santander.com` (FY2025) — the taxonomy identifier, not just the host.
- IPP instances additionally import `xbrldi-2006` (dimension instance) — pinned.
- CNMV IPP package covers all four models (`ipp_en`, `ipp_ge`, `ipp_se`, `ipp_ti`); corpus needs
  `ipp_en` + `ipp_ge` only.
- **R11 addendum — transitive dependencies pinned.** The first offline Arelle load (R11) proved the
  ESMA packages are not self-contained: `esef_cor.xsd` imports the **IFRS `full_ifrs` taxonomy**
  (`https://xbrl.ifrs.org/taxonomy/<ver>/full_ifrs/...`) and the **xbrl.org LEI module**
  (`lei-required.xsd`). Without them the DTS is incomplete (`missingReferences`). The official
  IFRS taxonomy ZIP requires IFRS Foundation login (OAuth redirect), so `pin_ifrs.py` pins every
  canonical `xbrl.ifrs.org`/`xbrl.org` file referenced by the ESMA packages **transitively**
  (43 files for 2022-03-24, 44 for 2024-03-27, 7 LEI files), with per-file SHA-256 in
  `evidence/ifrs_pinning.json`, and assembles local taxonomy packages
  (`*-opencnmv-pkg.zip`, `META-INF/catalog.xml` `rewriteURI` — same mechanism ESMA uses) so Arelle
  resolves them offline. Three manifest rows added (20 rows total).

## Toolchain pin

- **Arelle `arelle-release == 2.44.0`** (`arelleCmdLine.exe --version` → `Arelle(r) 2.44.0 (64bit)`),
  Python 3.12, invoked headless; taxonomy resolution via the pinned packages
  (package ZIPs + catalog rewrite), never live network, for R14/R15 determinism.
- Package loading entry points: ESMA `taxonomy/<date>/esef_cor.xsd` (+ issuer extension `.xsd`
  inside the artefact package); CNMV `ipp_{en,ge}_2019-01-01.xsd`.

## Limitations

- The issuer extension `source_url` values are taxonomy **identifiers**; bytes come from the
  preserved artefact package (catalog-rewritten), not from a live issuer-domain fetch.
- ESMA publishes taxonomy updates; the pinned `2022 v1.1` / `2024` ZIPs are what the corpus
  filings reference today — a changed SHA-256 on re-check means the source changed (flag, never
  overwrite).

## Evidence

- `taxonomy_manifest.json` (20 rows), `evidence/` (2 ESMA packages, 1 CNMV package copy,
  8 xbrl.org files, 3 locally-assembled packages + raw canonical file trees
  `ifrs-taxonomy-*/` and `xbrl-lei-*/`), `evidence/ifrs_pinning.json`,
  `pin_taxonomies.ps1`, `pin_ifrs.py`
