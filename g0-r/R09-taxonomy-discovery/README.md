# R9 — TAXONOMY_DISCOVERY

**Gate:** R9 — TAXONOMY_DISCOVERY
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`

## Objective

For each corpus artefact determine the taxonomy, taxonomy version, namespace, and required
packages/resources — by **content sniffing** (never by file extension). Produce a matrix, not
general-purpose code.

## Method

`taxonomy_discovery.ps1` reads `artifact_manifest.json`, sniffs each raw artefact's bytes
(reading the head, not trusting the `.zip`/`.xhtml` extension), and extracts the root namespace /
inline-XBRL markers, `schemaRef`, taxonomy namespace + date/version, model family, and external
dependencies. Output: `evidence/taxonomy_matrix.json` + `.csv`.

> Rule applied: **never decide the parser by the evidence file extension.** The raw files are named
> `.zip` but the IPP ones are pure XBRL XML and the ESEF ones are XHTML. Content/media_type is the
> arbiter.

## Matrix summary

### IPP (15 artefacts) — all `text/xml`, taxonomy `2019-01-01` (Circular 3/2018)

| Issuer | schemaRef | namespace | model |
|---|---|---|---|
| SAN | `http://www.cnmv.es/xbrl/ipp/en/2019-01-01/ipp_en_2019-01-01.xsd` | `…/ipp/en/2019-01-01` | `ipp_en` (entidades/credit model) |
| BBVA | `…/ipp/en/2019-01-01/ipp_en_2019-01-01.xsd` | `…/ipp/en/2019-01-01` | `ipp_en` (entidades/credit model) |
| IBE | `http://www.cnmv.es/xbrl/ipp/ge/2019-01-01/ipp_ge_2019-01-01.xsd` | `…/ipp/ge/2019-01-01` | `ipp_ge` (general model) |

- **H1 vs H2 falsified (same taxonomy):** every period (H1 and H2) for a given issuer uses the same
  taxonomy/namespace. The H2 files being much smaller is due to **fewer facts**, not a different
  taxonomy (e.g. SAN H2-2025 = 392 KB but uses `ipp_en/2019-01-01`, same as H1-2026).
- **SAN/BBVA vs IBE confirmed (model difference):** SAN/BBVA (credit institutions) use `ipp_en`
  (entidades model); IBE (general issuer) uses `ipp_ge` (general model). Discovered from the
  namespace/`schemaRef`, not from the issuer name. This is the credit-entity vs general-model
  distinction for R12.
- Entity identifier scheme confirms issuer NIF: `http://www.cnmv.es/xbrl/ipp/<NIF>`.

### ESEF (6 artefacts) — the downloaded `?e=` artefact is the **cover page**

- The R7 ESEF artefacts (`application/xhtml+xml`, `.zip`-named) are the **"Portada" (cover)**
  component: **no `ix:` markers, no `schemaRef`** — pure XHTML.
- The actual **inline-XBRL report** is a **separate component** in the same `ListadoIFA` row
  ("Individual" / "Consolidada"), and the **ZIP/Xbri package** (real `application/zip`) carries the
  extension taxonomy.
- **Consolidated iXBRL `schemaRef` (issuer extension taxonomy), FY2025:**
  - SAN: `http://www.santander.com/20251231/5493006QMFDDMYWIAM13-2025-12-31.xsd`
  - BBVA: `http://www.bbva.es/20251231/K8MS7FD7N5Z2WQ51AZ71-2025-12-31.xsd`
  - IBE: `http://www.iberdrola.com/20251231/5QK37QC7NWOJ8D7WVQ45-2025-12-31.xsd`
- Each uses the ESMA ESEF base taxonomy + the issuer's **extension taxonomy** (domain = issuer,
  date `20251231`, LEI-named). So the ESEF iXBRL report requires the issuer extension taxonomy
  **and** the ESMA base taxonomy package for offline reconstruction.

## Findings

1. IPP taxonomy version is uniform: `2019-01-01` (Circular 3/2018) across the corpus.
2. Two IPP model families: `ipp_en` (SAN/BBVA, credit/entidades) vs `ipp_ge` (IBE, general).
3. H1/H2 share the same taxonomy; H2 size is facts, not taxonomy.
4. ESEF: cover page has no taxonomy; the iXBRL + ZIP/Xbri package (with the issuer extension
   taxonomy) are separate components. The XHTML cover alone is **insufficient** for offline
   reconstruction — the **ZIP/Xbri package (extension taxonomy) is a required dependency** → feeds
   **R10** (raw/pinned with SHA-256). This is not a retroactive R7 failure; R7 correctly preserved
   the raw bytes.

## Limitation

The ESEF rows are characterised for FY2025; FY2024 uses the analogous `20241231` extension
taxonomy. The extension taxonomy URLs are external (issuer domains) and must be fetched/pinned in
R10 for offline determinism.

## Evidence

- `evidence/taxonomy_matrix.json`, `evidence/taxonomy_matrix.csv`
- The SAN/BBVA consolidated iXBRL `schemaRef` values are recorded above (in the matrix/README);
  the underlying 80 MB / 63 MB XHTML proof files were not retained in the repo (GitHub recommends
  <50 MB) but are re-downloadable from the stable `?e=` token in `ListadoIFA`.
- `g0-r/R07-raw-retrieval/artifact_manifest.json`, `taxonomy_discovery.ps1`
