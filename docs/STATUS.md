# STATUS.md — OpenCNMV session status

> **Operational state only.** This file records current gates, checkpoint, blocking findings and
> next action. It is **not** the source of truth for criteria. The authority for gates, corpus,
> scope and acceptance criteria is `AGENTS.md` + `docs/gates/G0-R.md` (+ `docs/PROJECT.md` for the
> model). Never edit this file first to change a criterion; decide gate verdicts against
> `docs/gates/G0-R.md`.

Update at the end of every session.

## Current phase

**G0-R** (CNMV Source & Reproducibility Probe) — R0–R4 closed; R0–R4 checkpoint `CONTINUE`.

## Gate statuses

```text
R0  PASS    # legal reuse
R1  PASS    # exact corpus enumeration -> artefact proven via listaifi/ListadoIFA (SAN/BBVA/IBE)
R2  PASS    # access mechanism characterised (use per-entity GET path; bypass general WebForms postback)
R3  PASS    # discovery stable across two observations (+ ListadoIFA byte-identical, ?e= tokens stable)
R4  PASS    # ARTIFACT_URL_STABILITY (remediated): real ESEF iXBRL + ZIP package + IPP byte-stable out-of-session; IPP ?t={GUID} ephemeral, nreg is the stable locator
R5  PASS    # issuer identity: NIF <-> legal entity <-> LEI, issuer != security (SAN/BBVA/IBE)
R6  PASS    # source filing key: nreg/registro = logical filing (best observed); substitution persistence NOT_YET_PROVEN -> R13
R7  PASS    # RAW_ARTIFACT_RETRIEVAL (remediated): 27 raw artefacts (15 IPP + 6 ESEF_COVER + 6 ESEF_PACKAGE_ZIP_XBRL); components enumerated
R8  PASS    # RAW_SHA256_STABLE (remediated): 27/27 MATCH on complete inventory; IPP re-resolved via nreg
R9  PASS    # TAXONOMY_DISCOVERY (remediated): IPP 2019-01-01 (ipp_en vs ipp_ge); ESEF FY2024+FY2025 schemaRefs observed; SAN domain changed
R10 PASS    # TAXONOMY_PINNING (amended by R11+R12): + IFRS full_ifrs 2022/2024 + LEI + IPP pkg + xl/xlink pinned as locally-assembled packages; manifest 23 rows; Arelle 2.44.0
R11 PASS    # ESEF_ARELLE_PARSE: 6/6 load offline (ioerr=0, DTS complete); Control A API-vs-OIM equal; Control B Arelle-vs-Brel concept containment (Brel partial oracle)
R12 PASS    # IPP_ARELLE_PARSE: 15/15 load offline (ioerr=0, DTS from pinned pkg only); ipp_en vs ipp_ge + H1/H2 covered; typed dims exercised; Control A equal; Arelle base64Binary MemoryError shimmed (also in 2.45.0)
R13 PASS    # SOURCE_REVISION_DETECTION: 13A REVISION_EXISTS + 13B REVISION_TARGET_EXACT (nregaud=registro, source-bound) + 13C semantics (IBE H1-2009 correction table); ESEF registro survives substitution (IBE FY2022 reg.19646) — R6 caveat closed for ESEF; IPP nreg persistence NOT_YET_PROVEN; R6 'empty column' claim corrected (Sí on 6/6 corpus rows = CERTIFICATE events, not revisions)
R14 PASS    # ONLINE_CAPTURE_DETERMINISTIC: 2 isolated runs (fresh Arelle caches, PYTHONHASHSEED 1 vs 777); source_state equal; discovery/manifest/taxonomy/events/facts logical hashes all equal; negative control differs; 21/21 facts byte-identical to R11/R12 evidence
R15 PASS    # OFFLINE_REBUILD_DETERMINISTIC (critical): zero discovery, 60 inputs sha256-verified pre-run, socket deny-all sentinel (preflight REACHABLE->DENIED), empty caches/profile, 0 connect attempts; A==B on all levels; A==R14 projections; facts==R11/R12 21/21; both starvation controls FAILED_AS_EXPECTED
R16 PASS    # ESEF_EXTERNAL_ORACLE_RECONCILIATION vs filings.xbrl.org: IBE-FY2024 EXACT_PACKAGE_MATCH (byte-identical incl. OIM facts); SAN/BBVA-FY2024 OPEN_CNMV_POSSIBLE_OMISSION (parallel -en OAM submission, ListadoIFA exposes only -es); FY2025 x3 ORACLE_OMISSION (index lag); 0 unexplained; BBVA es-vs-en sign diff on Equity@2023-01-01 recorded
R17 PASS    # H2_VS_ESEF_PERIOD_RECONCILIATION: 6 pairs; H2 nreg != FY registro, same period_end; scope from declared Modelo/Estadistico (banks HYBRID, IBE FULL); CURRENT_HALF!=YTD in all H2; naive concept+period_end key collides 265-532x/filing vs canonical 0; IPP vs ESEF concept sets disjoint; H2-revision model representable (Circular 3/2018 + Metrovacesa fixture)
```

## Checkpoint

```text
R0–R4 CHECKPOINT: CONTINUE
```

`CONTINUE` authorises proceeding to **R5** (within G0-R). **G1 is not touched** until the final
G0-R verdict (after R17) is `GO`. The final verdict states are `GO` / `CONDITIONAL_GO` / `NO_GO`.

## Resolution-session findings (R1/R4)

- **R1 PASS:** exact enumeration proven for all three issuers:
  - IPP (`listaifi?nif=`): stable `nreg` per period; SAN/BBVA/IBE each expose 60 `nreg`, including
    the corpus slots H1-2024…H1-2026.
  - ESEF (`ListadoIFA?nif=`): stable `registro oficial`; SAN FY2025=20875/FY2024=20509,
    BBVA FY2025=20854/FY2024=20448, IBE FY2025=20934/FY2024=20515.
- **R4 PASS:** both families byte-stable out-of-session for all three issuers (identical SHA-256
  across repeated downloads). The 18 ESEF `?e=` tokens are identical between visits.
- **Critical model rule:** the IPP `?t={GUID}` is **ephemeral** (changes per visit) but always
  redirects to the same stable `?e=` token and the same bytes. Canonical identity must use `nreg`
  (IPP) / `registro oficial` (ESEF) as `source_registration_no`; **never** `?t={GUID}`.

## Session-2 findings (R5–R8)

- **R5 PASS:** identity = issuer (legal entity) + identifiers (NIF, LEI); issuer != security.
  SAN=NIF A39000013/LEI 5493006QMFDDMYWIAM13; BBVA=A48265169/K8MS7FD7N5Z2WQ51AZ71;
  IBE=A-48010615/5QK37QC7NWOJ8D7WVQ45.
- **R6 PASS:** `nreg` (IPP) / `registro oficial` (ESEF) identify the logical filing
  (`source_registration_no`), stable across substitutions; `?e=` = per-version locator;
  `?t={GUID}` = ephemeral transport (never identity). No in-corpus substitution present to
  falsify against; semantics taken from the source legend.
- **R7 PASS:** 21 raw corpus artefacts materialized (15 IPP `text/xml` + 6 ESEF `application/xhtml+xml`)
  with HTTP metadata + `source_registration_no`. Observed: IPP H2 artefacts are much smaller than H1
  (potential model/taxonomy heterogeneity for R9/R12).
- **R8 PASS:** 21/21 artefacts byte-stable on re-download (SHA-256 match).
- **R9 PASS:** taxonomy discovery. IPP = 2019-01-01 (Circular 3/2018), model `ipp_en` (SAN/BBVA,
  credit) vs `ipp_ge` (IBE, general); H1/H2 same taxonomy (size = facts). ESEF iXBRL references an
  issuer extension taxonomy (santander.com / bbva.es / iberdrola.com, `20251231`) + ESMA base;
  the R7 ESEF artefacts are cover-only (no ix:/schemaRef); the ZIP/Xbri package (extension
  taxonomy) is a required dependency -> feeds R10.
- **R6 caveat:** `nreg`/`registro` = best observed `source_registration_no` (unique + stable across
  observations); **stability across a real substitution = NOT_YET_PROVEN, deferred to R13.**
- **R9 finding (reopens R4/R7/R8):** the six ESEF artefacts downloaded in R7 (and hash-tested in R8,
  and claimed as iXBRL in R4) are the **Portada (cover)** XHTML — **no `ix:`/`schemaRef`**. The real
  inline-XBRL report and the ZIP/Xbri package are **separate components** in the same `ListadoIFA`
  row. So R4/R7/R8's ESEF claim was misclassified; the inventory was incomplete.
- **Model insight:** 21 filings ≠ 21 artefacts. An ESEF filing has multiple artefacts:
  `COVER`, `IXBRL_CONSOLIDATED`, `IXBRL_INDIVIDUAL` (if applicable), `ESEF_PACKAGE_ZIP_XBRL`.
- **R17 finding (recorded, not executed):** SAN H2-2025 IPP contains `Dcur_PeriodoCorrienteActualMiembro`
  (2025-07-01→2025-12-31) and `Dcur_AcumuladoActualMiembro` (2025-01-01→2025-12-31) — same period_end,
  different temporal semantics (see `docs/findings/0002-*.md`).

## Remediation (R4/R7/R8/R9) — after the R9 reopening

- Enumerated all ESEF components per filing (Individual / Consolidada / ZIP-Xbri / Informe especial).
- Added 6 ESEF_PACKAGE_ZIP_XBRL (self-contained: iXBRL + issuer extension taxonomy + META-INF), ~10-34MB, SHA-256 recorded.
- The 6 IXBRL_CONSOLIDATED (real inline-XBRL) are byte-stable out-of-session (run1==run2); raw preserved inside the ZIP packages (standalone XHTML too large to store as a repo file).
- Reclassified the 6 covers as ESEF_COVER (hashes/provenance preserved).
- **Key finding:** the IPP `?t={GUID}` is ephemeral — re-downloading a stored `?t=` URL returns EMPTY. IPP must be re-resolved via `nreg` → detail → fresh GUID (discovery). Confirms R6 (`nreg` is the stable locator, not the URL).
- **SAN extension taxonomy domain changed** between years (santanderbank.com FY2024 → santander.com FY2025).
- R8 now verifies 27/27 MATCH on the complete inventory.
- **Post-remediation audit fixes (evidence consistency):**
  - `esef_components.json` `registro` corrected — the scraper's page-global `>(\d{5})<` had captured the **AUDITA column** (audit-report numbers: 18359/17877…), not the registro oficial. Verified per-row against preserved `ListadoIFA` evidence: SAN 20875/20509, BBVA 20854/20448, IBE 20934/20515. `remediate_esef.ps1` now parses registro+tokens from the same `<tr>`.
  - `ESEF_COVER.source_registration_no` placeholders (`registro-SAN-FY2025`) corrected to the official registro in `artifact_manifest.json` and `sha256_verify.json`.
  - `taxonomy_matrix.json` regenerated over the 27-artifact inventory (covers `XHTML_COVER_ONLY`; packages `ESEF_ZIP_PACKAGE` with `has_ix`/`schemaRef` observed inside each ZIP). FY2024 schemaRefs observed, not "analogous".
  - R4 evidence files renamed: `esef-IBE-consolidated_run*.zip` etc. contained the **cover**, now `esef-*-cover_run*.zip`.
- **Artifact model decision (verified):** the `reports/*.xhtml` member inside each ESEF ZIP package is **byte-identical** to the standalone consolidated XHTML served by the direct `?e=` link (`ixbrl_member_equality.json`, 6/6). So `IXBRL_CONSOLIDATED` = *package member + direct CNMV view*, not a separately persisted artefact; persisted inventory stays **27** (`package_member_path`/`member_sha256`/`byte_equal` recorded).

## Session-4 findings (R10/R11)

- **R10 PASS:** all taxonomy dependencies pinned (20 rows): CNMV IPP 2019-01-01, ESMA ESEF
  2022-03-24 (FY2024) / 2024-03-27 (FY2025), 8 xbrl.org base files, 6 issuer extensions
  (package members), Arelle `arelle-release==2.44.0`.
- **R10 amended by R11:** `esef_cor.xsd` transitively imports the IFRS `full_ifrs` taxonomy
  (2022-03-24 / 2024-03-27) and the xbrl.org LEI module (2020-07-02). Without them the offline
  DTS was incomplete (`missingReferences`). The official IFRS ZIP requires IFRS Foundation
  login, so canonical per-file downloads were pinned (43+44 IFRS, 7 LEI) and assembled into
  local taxonomy packages (`META-INF/catalog.xml` rewriteURI — the same mechanism ESMA uses).
- **R11 PASS:** conformance/integration test over Arelle (no custom parser). All 6 ESEF packages
  load offline with `internetConnectivity="offline"` + `validate/ESEF` +
  `saveLoadableOIM`: ioerr=0, DTS complete, facts 833–1952/filing, contexts 59–329,
  explicit dimensions preserved (corpus has no typed dims), `xml:lang` preserved.
  - **Control A** (Arelle Python API vs Arelle OIM xBRL-JSON): normalized fact multisets,
    concept coverage, decimals/nil distributions — equal on 6/6.
  - **Control B** (Arelle vs Brel 0.8.2a1 on SAN-FY2025): Brel's 363 concepts fully contained
    in Arelle's 403 (`concepts_only_brel=0`). Brel drops facts without iXBRL `format` and
    surfaces no dimensions → **partial oracle only, never authoritative**.
  - Both ESMA packages cannot load simultaneously (`tpe:packageRewriteOverlap`); sessions run
    per filing — recorded as an operational constraint for R14/R15.
  - Brel installed in isolated `.venv-brel` inside the gate dir (its pins conflict with the
    main env); the global env was restored after an accidental global install.

## Session-5 findings (R12)

- **R12 PASS:** all 15 IPP instances parse offline under Arelle 2.44.0. Deliberate coverage:
  `ipp_en` credit model (SAN/BBVA, 1262 DTS concepts) vs `ipp_ge` general (IBE, 869), H1+H2
  across all five corpus slots; **typed dimensions exercised** (1–16 typed-dim contexts per
  filing — absent in the ESEF corpus). Control A (API vs OIM) multiset-equal on 15/15.
- **Arelle limitation found & documented:** `lexicalPatterns['base64Binary']` raises
  `MemoryError` on the ~8 MB embedded-PDF `base64BinaryItemType` facts that IPP instances
  carry; identical regex in 2.45.0 → pin unchanged. Harness substitutes a linear-time
  equivalent lexical check (facts preserved raw, sha256+len recorded).
- **Entrypoint quirk:** raw IPP artefacts are XML stored with `.zip` suffix → Arelle treats
  them as archives; harness feeds byte-identical `.xbrl` copies (sha256-verified, deleted).
- **R10 amended by R12:** CNMV IPP flat zip re-wrapped as taxonomy package
  `cnmv-ipp-2019-01-01-opencnmv-pkg.zip` (CNMV + all pinned xbrl.org bases under
  rewriteURI); `xl-2003-12-31.xsd`/`xlink-2003-12-31.xsd` newly pinned (transitive imports
  of xbrl-linkbase). Every DTS doc now resolves from the package — no dependence on
  Arelle's per-user web cache (matters for R15).

## Session-6 findings (R13)

- **R13 PASS** (`g0-r/R13-source-revision-detection/`):
  - **13A:** all 6 corpus ESEF rows carry `Ampliación información = Sí` — each resolves to a
    `CERTIFICATE` event (formulación y firma), i.e. `Sí` ≠ revision. Fixture IBE FY2022
    (registro 19646): `CERTIFICATE` + `SUBSTITUTION` (28/02/2023).
  - **13B:** `infadicionifa` URL binds `nreg` (info-complementaria submission) → `nregaud`
    (= target's Nº Registro Oficial); param ≡ page registro ≡ row registro on 7/7 pages —
    exact, source-provided, no issuer+period inference. **ESEF registro persists across a
    real substitution** (fecha_publicacion = last-substitution date, per legend, now
    observed). Closes the R6 caveat **for ESEF only**; IPP `nreg` persistence =
    `NOT_YET_PROVEN` (`listaifi` has no revision surface — 2 columns only).
  - **13C:** IBE H1-2009 IPP PDF — deterministic `pypdf` extraction of "II. INFORMACIÓN
    COMPLEMENTARIA": nature, reason (escisión → discontinued ops → comparative restatement),
    corregida/previa/diferencia amounts (consolidated + individual), affected periods.
  - **R6 correction:** "Ampliación información empty for every corpus row" was an
    observation error — the R1 snapshot itself has `Sí` on all 6 corpus rows; row-level
    ampliación set identical between R1 snapshot and R13 re-fetch (no semantic drift).
  - Limitation: the listing serves only the current version of a filing; no
    superseded-version locator found.

## Session-7 findings (R14)

- **R14 PASS** (`g0-r/R14-online-capture-deterministic/`): adversarial determinism test with a
  preregistered hash scope (`hash_scope.json`). Two isolated online captures (distinct temp
  roots, empty per-run Arelle caches via `TMP` redirect, `PYTHONHASHSEED` 1 vs 777):
  `source_state` equal → all five logical levels equal (discovery, artifact manifest,
  taxonomy selection, events, fact inventory). Negative control (`+retrieved_at`, `+?t=GUID`)
  differs as required. `?e=` in scope and stable. Bonus: run-A `facts.jsonl` byte-identical
  to committed R11/R12 evidence (21/21) — cross-session determinism.
- Model note folded into R13 README: `infadicionifa` rows are `revision_event`s attached to
  the filing; `CERTIFICATE→creates_version_transition=false`, `SUBSTITUTION→true` — the six
  corpus `Sí` create no fictitious `filing_version`s.
- Arelle `base64Binary` MemoryError has a kept synthetic reproducer
  (`g0-r/R12-ipp-arelle-parse/arelle_base64_reproducer.py`); upstream issue to be filed
  after R15/G0-R close (no existing upstream issue found; regex identical in 2.45.0).

## Session-8 findings (R15)

- **R15 PASS** (`g0-r/R15-offline-rebuild-deterministic/`) — the critical gate. Closed input
  set (27 raw artefacts + R10 pinned/derived taxonomy packages + R13 preserved pages +
  harness code + Arelle 2.44.0 + gated shim), all sha256-verified before processing.
  Process-level network denial: unguarded preflight REACHABLE (host online) → socket
  deny-all sentinel → guarded preflight DENIED; 0 post-guard connect attempts; dead-proxy
  env; empty per-run caches **and** user profile (the read audit caught Arelle touching
  `%LOCALAPPDATA%\Arelle\plugins.json` despite the TMP redirect — fixed by redirecting
  USERPROFILE/APPDATA/LOCALAPPDATA/HOME into the run root).
- Triple binding: offline_A == offline_B (PYTHONHASHSEED 11 vs 999) on all levels;
  offline_A == R14 canonical projections (artifact manifest, taxonomy, events,
  facts_index, source_state); offline_A facts byte-identical to committed R11/R12 (21/21).
- Dependency starvation: `esef_taxonomy_2024.zip` removal → IOerror + 327 unresolved
  concepts → FAILED_AS_EXPECTED; `xl-2003-12-31.xsd` removal from the derived IPP package
  → IOerror + 181 xmlSchema errors → FAILED_AS_EXPECTED. The pinned set is load-bearing.
- Honest limits: denial is process-level, not an OS firewall rule (no elevation); the
  read audit covers Python `open()` only. Discovery is not rebuilt offline — R14's
  `source_state` is the provenance reference.
- **Central claim now demonstrated:** the captured CNMV financial data can be rebuilt
  deterministically with no dependence on CNMV/ESMA/xbrl.org availability or any
  machine-local cache.

## Session-9 findings (R16)

- **R16 PASS** (`g0-r/R16-esef-external-oracle/`) — reconciliation vs `filings.xbrl.org`
  (oracle-only) keyed on LEI+period_end+ESEF+ES, full LEI history per issuer, 4-level
  comparison (package sha256 → member manifest → iXBRL member → OIM fact multiset).
- **EXACT_PACKAGE_MATCH** IBE-FY2024: oracle package sha256 byte-identical to CNMV raw
  (89DFD3EF…); 833/833 OIM facts equal → oracle ingests CNMV bytes unchanged here.
- **Coverage finding (opened, not hidden):** SAN/BBVA FY2024 — the oracle's ES filing is
  a **parallel `-en` language-variant OAM submission** (distinct iXBRL, translated
  extension taxonomy; SAN changes namespace santanderbank.com→santander.com). CNMV
  ListadoIFA exposes exactly one ZIP per registro — the `-es` package our corpus holds.
  Shared ifrs-full undimensioned numeric core 68%/59% proves same underlying report.
  → `OPEN_CNMV_POSSIBLE_OMISSION` ×2: our corpus does not cover the `-en` submission;
  feeds the final G0-R verdict as a corpus-completeness caveat.
- **Real content divergence between issuer submissions:** BBVA `ifrs-full:Equity`
  @2023-01-01 [FinancialEffectOfChangesInAccountingPolicyMember] = **-98M in `-en` vs
  +98M in `-es`**. Between-submission difference, not a processing artifact.
- **ORACLE_OMISSION ×3** for FY2025: no ES filing indexed (ingestion lag — ES-2024
  arrived ~May-2025; SAN GB-2025 arrived 2026-03-04; oracle docs admit incompleteness).
- SAN GB (FCA) packages share 0 members with CNMV packages — distinct submissions, no
  silent dedup. Oracle `sha256` field verified == served package sha256 on all downloads.

## Session-9 findings (R17 + final G0-R)

- **R17 PASS** (`g0-r/R17-h2-vs-esef/`) — 6 H2↔FY pairs. H2 (IPP nreg) and FY (IFA
  registro) are distinct filings sharing issuer+FY+period_end. Every H2 filing carries
  CURRENT_HALF (Jul→close) **and** YTD (Jan→close) fact families plus prior-year
  comparatives — `concept+period_end` is falsified as an identity key (265–532 naive
  collisions/filing; canonical context-aware key: 0 collisions). `submission_scope`
  classified from declared `Modelo`/`Estadistico` (banks ECR/S → HYBRID_OR_REFERENCED;
  IBE GEN/N → FULL). IPP vs ESEF concept sets are disjoint — no automatic mapping.
  H2-revision model demonstrated with two evidence levels kept separate:
  `NORMATIVE_RULE` (Circular 3/2018 IFA→H2 resubmission trigger) and `SOURCE_OBSERVED`
  (Metrovacesa: H2-2025 reg 39018 + IFA reg 39038 on 24/02/2026; H2 modification reg
  39246 on 26/02/2026 — trigger not asserted as IFA-caused).
- **G0-R FINAL VERDICT: GO** — under the thesis "canonical and reproducible layer over
  filings exposed through the selected official CNMV surfaces". All 18 gates PASS.
- **Binding G1 finding: `LANGUAGE_VARIANT_COVERAGE_UNRESOLVED`** — parallel `-en` OAM
  submissions exist (R16) and are not interchangeable translations (BBVA sign diff).
  Prohibited public claim: "complete CNMV/OAM ESEF coverage". First G1 investigation:
  discover + model all OAM submission variants per issuer/period/language without
  collapsing divergent variants (`submission_variant` on the model).
- Pending housekeeping (not gates): upstream Arelle issue for the base64Binary
  MemoryError (reproducer kept in R12); `_runs/` dirs may be deleted now that all
  hashes/projections are committed.

## Blocking findings

- None for the R0–R4 checkpoint. Long-horizon token/URL drift is monitored by re-running the R8
  verification periodically.

## Corrected corpus (accepted)

```text
SAN / BBVA / IBE

ESEF
  FY2024
  FY2025

IPP
  H1-2024  H2-2024
  H1-2025  H2-2025
  H1-2026
```

Q1/Q3 ≥ 2021-05-03 → `NOT_REQUIRED_AS_IPP` (not `NOT_FOUND`). Voluntary quarterly → `OUT_OF_SCOPE_G0`.

## Issuer identity (fixed)

```text
SAN  BANCO SANTANDER, S.A.                 nif=A39000013
BBVA BANCO BILBAO VIZCAYA ARGENTARIA, S.A. nif=A48265169
IBE  IBERDROLA, S.A.                       nif=A-48010615  LEI=5QK37QC7NWOJ8D7WVQ45
```

## Next action

**G0-R closed and frozen at tag `g0-r-go` (`15c4778`): 18/18 PASS → final verdict `GO`.**
The verdict authorises G1 *design* only. G1 framing lives in `docs/G1.md`.

**G1-A `OAM_VARIANT_DISCOVERY`: PASS** (`g1/G1-A-oam-variant-discovery/`).
The `-en` variants are officially discoverable on the same CNMV surfaces
(`busqueda?id=25`, `listadoifa`) via the `lang=en` interface — `verdocumento`
tokens are language-dependent and resolve to the `-en` document set. All 6
in-scope registros share `nregaud`, submission `nreg`, dates and
`infadicionifa` history; per-filing verdicts: `DUAL_VARIANT_SHARED_REGISTRY`
(SAN, BBVA ×4) and `SINGLE_VARIANT_WITH_UI_FALLBACK` (IBE ×2 — `lang=en`
resolves to `-es`, `submitted_variant_count=1`). UI view ≠ submitted variant. Model: orthogonal axes are the
least-assumptive provisional shape — the lifecycle ordering is **not**
experimentally falsified (would need a variant-only substitution). SAN-FY2024
`-en` is byte-identical to the oracle copy (sha `47923b30…`); SAN-FY2025 `-en`
exists at CNMV though the oracle never indexed it. R16's
`OPEN_CNMV_POSSIBLE_OMISSION` is now a confirmed, explained omission of the
`lang=es`-only capture.

**G1-B `DUAL_LANGUAGE_CAPTURE`: PASS** (`g1/G1-B-dual-language-capture/`,
8/8 checks). Dual-lang capture with content-based `variant_artifact_set_id`;
4 filings × 2 variants, IBE ×2 = 1 variant + `FALLBACK_TO_ES` (adversarial
bad-model control proves the phantom-EN failure). 10 unique packages parsed
offline (Arelle 2.44.0, Control A equal, ioerr=0). Cross-variant comparison:
BBVA `Equity` +98M/−98M → `DIVERGENT_SUBMISSION_FACT` (mandatory test);
SAN `0.9`/`0.900` → `MATCH_NUMERIC_EQUIVALENT`; 683 textual pairs →
`LANGUAGE_SENSITIVE_NOT_COMPARED`; extension facts `UNMAPPED` (0 shared
extension QNames even where ns identical — justified empirically);
2,448/2,453 `VARIANT_ONLY` driven by extension dim members. Determinism:
capture A==B, extraction run1==run2, dataset rebuild identical.
`LANGUAGE_VARIANT_COVERAGE_UNRESOLVED` is closed for the in-scope corpus.

**G1-C `EXTENSION_VARIANT_IDENTITY`: PASS**
(`g1/G1-C-extension-variant-identity/`, 8/8 checks). Cross-variant pairing
of issuer-extension elements (fact concepts + dimension members) on
structural DTS evidence only — anchoring sets, XBRL properties,
presentation/calculation/definition path signatures; two-tier (unordered →
order-disambiguated), mutually-unique required, labels never read. Verdicts:
415 PROVEN_EQUIVALENT / 11 AMBIGUOUS (real shared-signature cases) /
2 CONFLICT / 21 UNMATCHED (evidence split: 138 tier-1 unique vs 277
order-disambiguated PROVEN). Mapped re-comparison of G1-B baseline:
UNMAPPED 4,239→132, VARIANT_ONLY 2,453→6, MATCH_EXACT 3,549→6,822,
NUMERIC_EQUIVALENT 1→9, DIVERGENT 1→1 (BBVA ±98M preserved, no new
divergences). Determinism: structure run1==run2, mapping + mapped dataset
rebuilds byte-identical.

**G1-D `VARIANT_LIFECYCLE_FALSIFICATION`: PASS**
(`g1/G1-D-variant-lifecycle-falsification/`, 11/11 checks). Scan of 96
official filings found exactly one dual-variant filing with a substitution:
TELEFONICA FY2024 (`nregaud` 20484). Its 2025-03-13 event is
`EN_ONLY_REPLACED` on explicit certificate text (published English
consolidated statements appeared in Spanish); the 2025-02-28 event stays
`VARIANT_SCOPE_NOT_OBSERVABLE` (individual-accounts scope, silent on
language). Verdict: `INDEPENDENT_VARIANT_LIFECYCLE_PROVEN` — a version_event
can affect a subset of submission_variants; `variant -> versions` gains
strong evidence and version events need an explicit affected-artefact scope.
AMPER/BANKINTER/URBAR substitutions are `SINGLE_VARIANT_WITH_UI_FALLBACK`
(cannot falsify). Caveat recorded: label-based substitution detection is a
lower bound — the decisive TEF event was labelled "otros".

**G1-E `CANONICAL_MODEL_FREEZE`: PASS**
(`g1/G1-E-canonical-model-freeze/`, 12/12 checks). Canonical model V1 frozen
as Pydantic schema + exported JSON Schema + invariants I1–I9 + four fixtures
rebuilt deterministically from frozen G1 evidence. Key correction vs G1-B:
`submission_variant.variant_id` (filing#language) is the stable identity;
`variant_version.artifact_set_id` is the per-version content identity.
`version_event.affects[]` reaches variant/component granularity with
nullable `source_nreg`. Spec: `docs/CANONICAL_MODEL_V1.md`. Tag
`g1-model-frozen`. **G1 DESIGN COMPLETE.**

**G2-A `DURABLE_CANONICAL_CORE`: PASS**
(`g2/G2-A-durable-canonical-core/`, 6/6 checks). New durable library
`src/opencnmv/` (model / source.cnmv / xbrl / canonicalize / provenance /
serialize) rebuilds all four frozen V1 fixtures **byte-identically** from
sha256-pinned evidence, offline (socket deny-all, 0 network calls), with a
meta-path blocker proving 0 imports from `g0-r/`/`g1/` code. Objects
conform to the frozen `canonical_model_v1.schema.json` — incompatible
changes require `CANONICAL_MODEL_V2`.

**G2-B `FULL_FROZEN_CORPUS_REBUILD`: PASS**
(`g2/G2-B-frozen-corpus-rebuild/`, 8/8 checks). The production adapter
(`opencnmv.xbrl.arelle` + `opencnmv.canonicalize.facts`) reparsed all 25
frozen XBRL states — 10 ESEF variant packages + 15 IPP instances — fully
offline: pinned Arelle 2.44.0 version check, one Session per filing,
fingerprint-gated base64 shim, sha-verified `.xbrl` entrypoint for the
`.zip`-suffixed IPP instances, isolated XDG_CONFIG_HOME/HOME/TEMP profile.
facts.jsonl is content-identical to the frozen R12/G1-B oracles (LF-
normalised; oracles were CRLF text-mode) with full multiset equality —
concept, entity, period, explicit+typed dims, complete unit num/den,
decimals, nil, xml:lang, value_sha256 — plus Control A (API multiset ==
Arelle OIM multiset, 25/25) and cross-PYTHONHASHSEED determinism
(identical corpus hash). Negative dependency controls fail as expected.

**G2-C `COLUMNAR_DATASET_V1`: PASS**
(`g2/G2-C-columnar-dataset-v1/`, 20/20 checks). New production module
`opencnmv.dataset` materializes the whole frozen corpus to deterministic
Parquet under `dataset/v1/` — 9 canonical-model tables (filing,
filing_version, submission_variant, variant_version, view_resolution,
version_event, event_affects, artifact, extension_mapping) plus
`facts` (45,376 rows; full canonical record set incl. duplicate-fact
multiset via deterministic `#occ` ids), `fact_dimension` (38,365
explicit+typed rows), `provenance` — plus `dataset_manifest.json`
(per-file sha256 + logical row hashes + corpus logical hash
`b2612152…045f69`) and `schema/*.json`. DuckDB is a read-view query
surface only; Parquet+manifest are authoritative. All 25 states
round-trip to the G2-B oracle multiset; all 4 frozen fixtures rebuild
byte-identically from columnar storage alone; all 22 filings validate
against the frozen JSON Schema + Pydantic. Run A == run B
byte-identical for every file (PYTHONHASHSEED 17 vs 991). BBVA
+98M/-98M divergence, IBE FALLBACK_TO_ES (no phantom #en), TEF EN
lifecycle and event scoping, H2 CURRENT_HALF/YTD dims, typed dims,
compound units (130 denominator-bearing facts), and the
PROVEN_EQUIVALENT-only rewrite gate all preserved. Negative controls:
naive concept+period_end keying would collapse 5,914 fact groups;
row-deletion and single-byte Parquet corruption both fail integrity/
manifest verification. New `dataset` extra: duckdb==1.5.5,
pyarrow==25.0.1 (locked, CI on both OS).

**G2-D `INCREMENTAL_UPDATE_SEMANTICS`: PASS**
(`g2/G2-D-incremental-update-semantics/`, 21/21 checks). New production
module `opencnmv.update`: `observe` (CANONICAL_OBSERVATION_V1 document —
complete canonical filing projection + states for newly introduced
variant_versions + removal-evidence dispositions; semantic hash excludes
capture metadata so re-capture replays identically), `classify` (pure
S0-rows + O1 -> transitions + row ops), `delta` (CANONICAL_DELTA_V1 —
self-hashed, bound to `base_corpus_logical_sha256`, predicts the result
hash), `apply` (stale-base check -> in-memory merge -> full dataset +
update integrity -> staged write -> manifest verify -> rename-swap
publish; staging is never authoritative), `integrity` (supersedes-chain,
event-scope, version-sequence invariants). Closed transition vocabulary
in `update/transitions.py`. Append-only ledger: superseded versions'
facts/artifacts are historical capture records — `ARTIFACT_REMOVED`/
`FACT_REMOVED` are delta-level semantic transitions, not deletions;
the only in-place updates are `created_by_event_id` backfill and
`extension_mapping` analysis fields (PROVEN-only `rewrites_identity`
recomputed by the engine, never trusted from input). 13 scenarios built
by decompiling the pinned G2-C dataset back into observation docs and
carving S0 bases by row subtraction: corpus-restoring scenarios must
reproduce the pinned corpus byte-identically; synthetic-state scenarios
are checked against an independent observation-union materializer.
Results: A/C1 replay NO_CHANGE; B NEW_FILING complete graph (1 filing +
1 version + 1 variant + 1 variant_version + 1 artifact + 1,110 facts +
1,174 dims + provenance); C2 fr->es FALLBACK records a view_resolution
row, no phantom variant; D BBVA #en variant + #en#v1 (1,847 facts, 125
mappings) with #es untouched; E TEF 20484 13/03 EN_ONLY_REPLACED ->
#en#v2 superseding v1, affects only #en; F 28/02
VARIANT_SCOPE_NOT_OBSERVABLE + created_by backfill; G fact payload
change preserves both payloads under distinct variant_versions; H1/H2
artifact absence -> UNRESOLVED / REMOVED_CONFIRMED -> row-retaining
annotation; I1 +119 mappings; I2 promote/demote updates 2 rows with the
adversarial `rewrites_identity` claim rejected; I3 shrunk mapping file
-> UNRESOLVED. Idempotent replay on every scenario; deltas byte-identical
across PYTHONHASHSEED 17 vs 991; stale-base -> StaleBaseError; tampered
delta -> DeltaError; corrupt observation -> ObservationError; 3 failure
injection points leave the prior dataset valid; classify/apply ran under
socket deny-all; incremental S1 byte-identical to the clean-rebuild
oracle on every applied scenario. Unit tests 15/15 (full suite 38/38);
ruff + mypy clean on 35 modules; sdist+wheel build + pip check.
Regressions on final HEAD: G2-A PASS 6/6, G2-B PASS 8/8, G2-C PASS 20/20.
Re-verified on HEAD `332ba96`: `g2d_verify.py` re-run -> 21/21 PASS against
the persisted `_out/` artifacts; third independent run (seed 31337, tag C)
reproduced every scenario's S0->S1 corpus hash and byte-identical deltas vs
run A; all fail-closed controls fired. unittest 38/38, ruff + mypy clean,
CI green on the pushed commit. Next: G2-E / CLI surface (per docs/G2.md
ordering).

## Engineering-hardening session (2026-09-17)

Not a gate. Packaging/QA/CI and repository hygiene for public distribution;
no gate criteria, verdicts, raw artefacts, or corpus changed.

- **Packaging:** `pyproject.toml` (setuptools src-layout, `opencnmv` +
  `[dev]`/`[xbrl]` extras), `requirements-dev.lock` (uv-compiled universal
  lock, exact transitive pins; Arelle 2.44.0 preserved), `CONTRIBUTING.md`
  with verified setup/check commands and ADOPT/WRAP dependency decisions.
- **Tests:** `tests/` — frozen-fixture byte equality via the G2-A builder in
  isolated subprocesses (socket guard intact), frozen JSON Schema + runtime
  Pydantic round-trip (`exclude_unset`), fact-identity sensitivity, issuer-
  picker ambiguity rejection with evidence, and retrieval size/deadline
  guards. 14/14 pass.
- **Static checks:** ruff (E4/E7/E9/F) and mypy (`check_untyped_defs`) clean
  on `src` + `tests`.
- **CI:** `.github/workflows/ci.yml` — Linux + Windows, Python 3.11, locked
  install, tests, ruff, mypy, sdist+wheel build, wheel reinstall + retest,
  `pip check`. Actions pinned by tag SHA.
- **Evidence hygiene:** machine-local paths removed from *generated* outputs
  only (`F:\_Proyectos\…` in R12/R15 result JSONs + `g0-r/README.md`;
  `C:\Users\…\venv` in G1-B run1 Arelle logs). No raw CNMV artefact touched.
  R15 + G1-B manifest hashes re-pinned; sanitization recorded in each
  manifest's `limitations`. Pre-sanitization bytes remain in git history.
- **`.gitattributes`:** `* -text` — manifests pin file sha256, so no EOL
  conversion may ever occur on checkout.
- `.gitignore` extended (venvs, dist/build, egg-info, tool caches,
  `opencode.json`). `SECURITY.md`, issue/PR templates added.
- **Gate re-verification on final HEAD `2784e00`** (after hardening touched
  `src/` + re-pinned evidence): **G2-A PASS 6/6**, **G2-B PASS 8/8** —
  all 25 frozen states rebuilt, run A == run B, byte-identical verify
  results; manifests updated to `code_commit 2784e00`. **GitHub Actions:
  Linux + Windows PASS** on the pushed commits.
- Next action: **G2-C `COLUMNAR_DATASET_V1`**.

## Session hygiene

- Update this file at the end of every session.
- Prefer small, explicit dependencies. Do not build general infrastructure.
