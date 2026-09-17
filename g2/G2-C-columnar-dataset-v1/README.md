# G2-C — COLUMNAR_DATASET_V1 (preregistered)

Materialize the complete frozen canonical corpus into a durable,
deterministic columnar dataset — without losing any semantics proven in
G0/G1/G2-A/G2-B. Storage gate only: no API/UI/MCP.

## Design

Authoritative materialized form = **Parquet files + dataset manifest +
schema JSON**, rebuildable offline from sha256-pinned evidence. DuckDB is
a query surface over the Parquet, never the authoritative store.

Model layer (small relational tables, one row per canonical entity):

```text
filing               1 row per canonical filing (22: 6 ESEF + 15 IPP + TEF)
filing_version       source submission records (nreg / filed_at / kind)
submission_variant   stable identity <filing_id>#<lang> (never a hash)
variant_version      content state <variant_id>#v<n> (artifact_set_id)
view_resolution      UI-language observations (NOT identity)
version_event        CERTIFICATE / SUBSTITUTION / ... (source_nreg nullable)
event_affects        variant/component-scoped effect of an event
artifact             artifact occurrence, owned by variant_version |
                     filing_version (IPP) | version_event (evidence docs)
extension_mapping    all G1-C mapping records + lossless record_json
provenance           fact/artifact -> preserved source evidence
facts                high-volume fact plane (full canonical record set)
fact_dimension       normalized dimension plane (explicit + typed)
```

Fixture-only presentation fields (`fact_examples`,
`extension_mapping_summary`, fixture-scoped `extension_mappings`) ride in
`filing.extras_json` — canonical JSON, lossless, overlaid on
reconstruction so the frozen G1-E fixtures rebuild byte-identically.

IPP filings (`cnmv:ipp:<nreg>`) get one implicit `es` variant; the raw
IPP_XBRL artifact attaches to `filing_version` per the V1 migration note
(CANONICAL_MODEL_V1.md: "G0 artifacts attach to filing_version (IPP)").
`issuer.nif` is populated for IPP filings; frozen ESEF fixtures carry only
denomination+lei and are preserved verbatim.

## Fact plane rules

* `fact_id` = `opencnmv.canonicalize.facts.fact_id` over the full
  structural key (concept | entity | period | dims | unit | language) +
  variant_version_id — never concept+period. The corpus is a true
  multiset (e.g. SAN-FY2024-es carries 4 identical
  CashAndCashEquivalents facts on context c-3): duplicate structural
  keys get a deterministic `#<occ>` occurrence suffix.
* Dimensions are normalized into `fact_dimension` with kind E/T,
  member_qname / typed_value — no lossy text blob.
* Units keep the canonical signature plus split numerator/denominator
  lists (all measures preserved).
* `facts` keeps the complete frozen record field set (value/xValue
  sha256+len+preview, esef-profile `value_full`/`xValue_full`, decimals,
  isNil, lang, contextID, unitID, concept_type, is_numeric, ns_kind) so
  the oracle JSONL is byte-reproducible from Parquet.

## Check matrix (preregistered)

```text
C1  materialize complete frozen corpus: 25/25 states parsed via the
    production path; 22 filings materialized; counts == oracle summaries
C2  referential integrity: all FK links resolve; PK uniqueness; no
    orphan rows; no duplicate identities
C3  facts preserve the full G2-B semantic multiset: per-state records
    reconstructed from Parquet == oracle facts.jsonl (byte-equal after
    LF normalization AND field-level multiset equality)
C4  the four frozen CANONICAL_MODEL_V1 fixtures reconstruct from columnar
    storage alone (canonical JSON byte-equal) and validate against the
    frozen JSON Schema
C5  BBVA Equity +98M/-98M cross-variant divergence preserved
C6  IBE: one submission_variant, FALLBACK_TO_ES view, no phantom #en
C7  TEF 20484: en v1(unobserved)->v2(observed); 13/03 event scopes only
    #en; 28/02 VARIANT_SCOPE_NOT_OBSERVABLE; source_nreg null on 13/03
C8  explicit + typed dimensions preserved (typed-dim facts queryable)
C9  compound units preserved (num/den split reconstructs signature)
C10 only PROVEN_EQUIVALENT mappings usable for identity rewrite;
    AMBIGUOUS/CONFLICT/UNMATCHED remain unresolved in storage
C11 DuckDB verification queries return expected deterministic results
C12 run A == run B: per-file sha256 identical (byte determinism) AND
    identical logical corpus hash
C13 dataset_manifest per-file sha256 + row counts verify
C14 zero network access (socket deny-all in workers + verifier paths)
C15 zero imports from g0-r/ / g1/ code in the production path
```

Negative controls:

```text
NC1 naive concept+period_end key collapses known H2 semantics
    (collisions > 0) while the production fact_id has 0 collisions
NC2 joining on requested UI language cannot create a phantom IBE #en
    variant (no such row; view_resolution resolves en->#es)
NC3 applying all version events filing-wide would wrongly mutate TEF es;
    stored affects scoping leaves es untouched
NC4 attempting identity rewrite through an AMBIGUOUS mapping is refused
NC5 deleting a relational row breaks integrity verification (orphans)
NC6 flipping one Parquet byte breaks manifest + logical-hash verification
```

## Execution

```sh
python g2c_materialize.py   # runA (PYTHONHASHSEED=17) + runB (991) ->
                            # _out/run{A,B}/dataset/v1 + manifests
python g2c_verify.py        # writes g2c_verify_results.json
```

Dataset Parquet lives under `_out/` (gitignored): the dataset is
deterministically rebuildable from pinned inputs; `dataset_manifest.json`
+ `schema/*.json` pin every file sha256 and the logical corpus hash.

## Results (executed)

All 20 checks PASS — see `g2c_verify_results.json` and `manifest.json`.

```text
filings materialized      22  (6 ESEF + 15 IPP + TEF 20484 lifecycle)
states parsed             25/25, net=0, ioerr=0, runA == runB
facts                     45376   fact_dimension rows  38365
model rows                filing 22, filing_version 23,
                          submission_variant 27, variant_version 28,
                          view_resolution 29, version_event 8,
                          event_affects 2, artifact 33,
                          extension_mapping 449, provenance 25
dataset size              ~4.6 MB (12 parquet + manifest + schema/)
corpus_logical_sha256     b2612152f46406a5ec4858592656c10b0afa8f98b042dc93337782b202045f69
determinism               run A == run B byte-identical for every file
                          (PYTHONHASHSEED 17 vs 991), not just logical hash
round-trip                25/25 states == G2-B oracle multiset;
                          4/4 frozen fixtures byte-equal; 22/22 filings
                          validate against frozen JSON Schema + Pydantic
BBVA divergence           160 divergent structural pairs incl. the
                          Equity +98M/-98M pair — preserved
mappings                  415 PROVEN_EQUIVALENT / 11 AMBIGUOUS /
                          21 UNMATCHED / 2 CONFLICT; 0 non-PROVEN rows
                          marked rewritable
units                     130 denominator-bearing facts; the corpus has
                          no multi-measure-numerator unit (lists fully
                          supported; exercised in unit tests)
naive-key control         concept+period_end collides on 5914 fact
                          groups — production schema unaffected
```

Limitations: Parquet outputs are generated artifacts under `_out/` (not
committed — reproducibility is pinned via dataset manifests + logical
hashes); IPP artifacts attach to `filing_version` per the V1 migration
note; unit numerator/denominator measures ride a worker sidecar
(`units.jsonl`) because canonical unit signatures embed `/` inside
QNames and cannot be split lexically; TEF 20484 is lifecycle evidence
only (no facts); Arelle worker logs are preserved per run but not
hash-pinned.
