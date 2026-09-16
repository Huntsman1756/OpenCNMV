# R12 — IPP_ARELLE_PARSE

**Gate:** R12 — IPP_ARELLE_PARSE
**Status:** `PASS`
**Executed:** 2026-09-16 (UTC)

## Objective

Per `docs/gates/G0-R.md`: *"Demonstrate IPP parsing with Arelle. Deliberately cover: credit-entity
model; general model; H1; H2; taxonomy/model heterogeneity actually observed within the frozen
corpus. Record taxonomy incompatibilities, do not hide them."*

Executed as a **conformance/integration test over Arelle**, reusing the R11 harness pattern —
no custom parser:

```text
IPP raw XBRL instance (R7, 15 artefacts)
          |
      Arelle 2.44.0  (pinned, R10)
          |
   +------+-------+
   |              |
ModelXbrl      saveLoadableOIM
Python API     xBRL-JSON
   |              |
   +--- compare --+          <- CONTROL A (adapter loses nothing vs OIM)
          |
   OpenCNMV evidence
```

## Runtime

- `arelle-release == 2.44.0` (Python API, `arelle.api.Session`), CPython 3.11.
- `internetConnectivity="offline"` — `ioerr=0`, zero download attempts on all 15 runs.
- `packages=[cnmv-ipp-2019-01-01-opencnmv-pkg.zip]` — locally-assembled taxonomy package
  (R10 addendum, `pin_ipp_pkg.py`): re-wraps the pinned flat CNMV zip under canonical
  `http://www.cnmv.es/xbrl/ipp/` paths **plus** the R10-pinned xbrl.org base schemas
  (`META-INF/catalog.xml` rewriteURI). Every DTS document resolves from pinned bytes — see
  `dts_resolution` per filing (13 package docs + 1 local instance); no reliance on Arelle's
  per-user web cache.
- `plugins="saveLoadableOIM"`, `validate=True`. No disclosure system (CNMV IPP has none in
  Arelle); XBRL 2.1 + Dimensions validation applies.

## Corpus coverage — 15 IPP instances (R7)

All required combinations are exercised by the frozen corpus itself:

| Axis | Coverage |
|---|---|
| credit-entity model `ipp_en` | SAN ×5, BBVA ×5 |
| general model `ipp_ge` | IBE ×5 |
| H1 | 2024, 2025, 2026 ×3 issuers |
| H2 | 2024, 2025 ×3 issuers |

## Results (`evidence/r12_results.json`, per-filing `*.model_summary.json`)

| Filing | model | facts | contexts | concepts (DTS) | ioerr | Control A |
|---|---|---|---|---|---|---|
| SAN-H1-2024 | ipp_en | 2934 | 135 | 1262 | 0 | true |
| SAN-H2-2024 | ipp_en | 2771 | 120 | 1262 | 0 | true |
| SAN-H1-2025 | ipp_en | 2961 | 135 | 1262 | 0 | true |
| SAN-H2-2025 | ipp_en | 2724 | 120 | 1262 | 0 | true |
| SAN-H1-2026 | ipp_en | 2455 | 135 | 1262 | 0 | true |
| BBVA-H1-2024 | ipp_en | 1679 | 133 | 1262 | 0 | true |
| BBVA-H2-2024 | ipp_en | 1866 | 120 | 1262 | 0 | true |
| BBVA-H1-2025 | ipp_en | 1674 | 133 | 1262 | 0 | true |
| BBVA-H2-2025 | ipp_en | 1875 | 120 | 1262 | 0 | true |
| BBVA-H1-2026 | ipp_en | 1686 | 133 | 1262 | 0 | true |
| IBE-H1-2024 | ipp_ge | 1121 | 94 | 869 | 0 | true |
| IBE-H2-2024 | ipp_ge | 1263 | 96 | 869 | 0 | true |
| IBE-H1-2025 | ipp_ge | 1114 | 94 | 869 | 0 | true |
| IBE-H2-2025 | ipp_ge | 1281 | 96 | 869 | 0 | true |
| IBE-H1-2026 | ipp_ge | 1110 | 94 | 869 | 0 | true |

Preservation demonstrated per filing (`*.facts.jsonl`, deterministic one-line-per-fact
inventory): fact QName, value/xValue (sha256+len+preview), decimals, nil, context
(entity scheme+id, start/end/instant/forever), unit, **explicit and typed dimensions**,
`xml:lang`, fact-footnote count.

## CONTROL A — Arelle Python API vs Arelle OIM export

Same normalised semantic fact key as R11, compared as multisets. All 15 filings:
`fact_count` equal, `fact_multiset_equal=true`, `concept_coverage_equal=true`,
decimals/nil distributions equal. The adapter loses nothing relative to Arelle's
standard OIM serialization.

## Findings

1. **All 15 IPP instances parse fully offline**: DTS complete (14 documents), `ioerr=0`,
   zero download attempts, **zero warnings or errors** (`log_code_counts` empty) under
   `validate=True`.
2. **Model heterogeneity is real and preserved**: `ipp_en` DTS exposes 1262 concepts,
   `ipp_ge` 869 — distinct models, not parameterisations of one schema. H1 vs H2 differ
   structurally in context/fact volume (e.g. SAN 135 vs 120 contexts; IBE 94 vs 96).
3. **Typed dimensions exist in the IPP corpus** (unlike ESEF, where they were 0):
   1–16 typed-dimension contexts per filing (e.g.
   `LineaPersonasResponsablesInformacionEje` → `T:10`). The typed-dim code path is
   exercised on real data here, and both `E:`/`T:` dimension kinds are preserved in
   the fact inventory.
4. **Arelle limitation (recorded, worked around at harness level):**
   `arelle.XmlValidate.lexicalPatterns["base64Binary"]` is a nested-quantifier regex
   (compiled with the third-party `regex` module, V0); on the ~8 MB
   `xbrli:base64BinaryItemType` facts the IPP instances embed (PDF bytes in
   `ipp_*:InformacionFinancieraSemestralContenido`, `ipp_*:InformeCompleto*_Contenido`)
   it raises `MemoryError` inside `instanceDiscover → xmlValidate` — i.e. at load, so
   `validate=False` cannot avoid it. The identical regex exists in `arelle-release`
   **2.45.0** (verified in the wheel), so upgrading does not fix it and the 2.44.0 pin
   stands.
   The harness substitutes a **linear-time validator that is deliberately fragile**:
   it installs only if `arelle-release==2.44.0` AND the original pattern is
   byte-identical to a recorded sha256 fingerprint — otherwise it fails loudly instead
   of patching over an unreviewed upstream change. Equivalence is proven at install
   time by a self-test against the **original pattern object**: 40 curated cases +
   4000 deterministic fuzz cases + a 12 MB payload (shim source sha256, original
   pattern sha256 and self-test results are recorded per filing under
   `runtime.lexical_shim`). Two real divergences were caught and fixed by the gate
   itself during development (regex-module `$`-before-`\n` quirk and the
   no-trailing-whitespace rule). The giant facts are preserved raw — e.g.
   SAN-H1-2024 `value_len=8 720 556`, sha256 recorded. Re-running all 15 filings with
   the hardened shim reproduced byte-identical `facts.jsonl` outputs (15/15).
5. **Entry-point quirk:** the raw IPP artefacts are XML instances stored with a `.zip`
   suffix; Arelle `FileSource` treats `.zip` as an archive (`FileSourceError BadZipFile`).
   The harness feeds a byte-identical `.xbrl` copy (sha256 verified equal to the raw
   artefact, deleted after the run). Raw bytes are never modified.
6. **R10 amended by R12:** the pinned CNMV zip is a flat file set (no `META-INF`), so it
   could not be loaded via `packages`. It is now re-wrapped as
   `cnmv-ipp-2019-01-01-opencnmv-pkg.zip` (canonical layout + catalog rewriteURI,
   same mechanism as the IFRS/LEI packages), and `xl-2003-12-31.xsd` /
   `xlink-2003-12-31.xsd` — transitive imports of `xbrl-linkbase` — were pinned
   (previously served implicitly by Arelle's caches).

## Limitations

- The lexical shim covers only `base64Binary` value validation (an XSD lexical check, not
  XBRL semantics); all other validation runs unmodified inside Arelle. It is version- and
  fingerprint-gated; a different Arelle version or a changed upstream pattern aborts the
  run rather than patching silently.
- `/se/` and `/ti/` paths inside the IPP package are mapped by analogy with the observed
  schemaRef pattern; the frozen corpus exercises only `/en/` and `/ge/`.
- No second-parser control on IPP: Brel (R11 Control B) was characterised as a partial
  oracle for iXBRL/ESEF and is not authoritative; Control A bounds adapter loss instead.
- OIM comparison uses xBRL-JSON (same convention as R11).

## Evidence

- `r12_parse.py` — harness (one Arelle `Session` per filing; `.xbrl` entrypoint copies in
  `evidence/_entrypoints/`, sha256-verified, deleted after each run).
- `evidence/<FID>.facts.jsonl` — deterministic API fact inventory (sha256 in model_summary).
- `evidence/<FID>.model_summary.json` — counts, namespaces, log codes, `dts_resolution`
  provenance, offline evidence, Control A verdict, output hashes.
- `evidence/<FID>.oim.json.gz` — Arelle `saveLoadableOIM` xBRL-JSON export.
- `evidence/<FID>.arelle-log.json` — Arelle log records.
- `evidence/r12_results.json` — aggregate results.
- `g0-r/R10-taxonomy-pinning/pin_ipp_pkg.py`, `evidence/ipp_pkg_members.json`,
  `evidence/cnmv-ipp-2019-01-01-opencnmv-pkg.zip` — assembled taxonomy package + member
  provenance.
