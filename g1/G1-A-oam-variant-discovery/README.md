# G1-A — OAM_VARIANT_DISCOVERY

**Status:** PASS (discovery answered for all 6 in-scope IFA registros)

G1-A is a discovery probe, not a product. It answers mechanically where the
`-en` ESEF variants live at CNMV and what identity they have, so that the
`submission_variant` model can be designed on evidence instead of assumption.

## Binding finding carried from R16

R16 classified SAN/BBVA FY2024 as `OPEN_CNMV_POSSIBLE_OMISSION`: the oracle
(`filings.xbrl.org`) indexed `-en` packages that our ListadoIFA-driven
capture never saw. G1-A resolves where those packages come from.

## Method

`filings.xbrl.org` declares its CNMV source as
`www.cnmv.es/Portal/consultas/busqueda.aspx?id=25` ("Informes financieros
anuales"). G1-A POSTs that official search twice per issuer — once with the
Spanish UI (`lang=es`), once with the English UI (`lang=en`) — and compares,
per registro oficial:

- visible row cells (dates, auditor, tipo, opinión),
- the opaque `verdocumento` document tokens,
- the `infadicionifa` (additional-information/history) link — which carries
  the submission entry number `nreg`,
- the SHA-256 of the ESEF ZIP package each language's tokens serve.

IBE is the control case (no `-en` in the oracle): `lang=en` is expected to
fall back to the `-es` package.

## Result matrix

**UI language view ≠ submitted variant.** `requested_ui_language=en` resolves
to whichever artifact set the registry serves for that view; when no English
filing exists the registry falls back to the `-es` set — a `FALLBACK`, not a
second `submission_variant`. The real outcome is:

```text
4 filings with 2 submitted variants:   SAN FY2024/FY2025, BBVA FY2024/FY2025
2 filings with 1 submitted variant:    IBE FY2024/FY2025
                                       (lang=en → resolved es, FALLBACK)
```

| Issuer | FY | registro | nreg (es==en) | pub date (es==en) | `-es` ZIP sha256 | `lang=en` resolved sha256 | resolution_mode(en) | verdict |
|---|---|---|---|---|---|---|---|---|
| SAN | 2024 | 20509 | 2025031067 == 2025031067 | 28/02/2025 == 28/02/2025 | `725fff01…` | `47923b30…` | SUBMITTED_VARIANT | DUAL_VARIANT_SHARED_REGISTRY |
| SAN | 2025 | 20875 | 2026029493 == 2026029493 | 25/02/2026 == 25/02/2026 | `07e95a16…` | `77ac614a…` | SUBMITTED_VARIANT | DUAL_VARIANT_SHARED_REGISTRY |
| BBVA | 2024 | 20448 | 2025022995 == 2025022995 | 14/02/2025 == 14/02/2025 | `69f04da4…` | `75be80e1…` | SUBMITTED_VARIANT | DUAL_VARIANT_SHARED_REGISTRY |
| BBVA | 2025 | 20854 | 2026023406 == 2026023406 | 13/02/2026 == 13/02/2026 | `675a1d3a…` | `40ff2f17…` | SUBMITTED_VARIANT | DUAL_VARIANT_SHARED_REGISTRY |
| IBE | 2024 | 20515 | 2025031726 == 2025031726 | 28/02/2025 == 28/02/2025 | `89dfd3ef…` | `89dfd3ef…` (same bytes) | FALLBACK_TO_ES | SINGLE_VARIANT_WITH_UI_FALLBACK |
| IBE | 2025 | 20934 | 2026031462 == 2026031462 | 27/02/2026 == 27/02/2026 | `066fdaf8…` | `066fdaf8…` (same bytes) | FALLBACK_TO_ES | SINGLE_VARIANT_WITH_UI_FALLBACK |

## Answers to the four questions

**Q1 — where is each variant officially discoverable?**
On the same CNMV surfaces already used (`busqueda.aspx?id=25` and
`listadoifa.aspx`), selected by the **interface language** `lang=es|en`.
Each registro row contains `verdocumento` tokens that resolve to different
documents depending on the UI language: `lang=es` → `-es` package,
`lang=en` → `-en` package when the issuer filed one, else the `-es`
package (observed fallback for IBE). The same behaviour applies to the
Individual/Consolidada XHTML viewer links. No separate registry listing,
sitemap, or internal API is needed — the `-en` is on the ordinary CNMV
visible surface, behind a UI-language switch.

**Q2 — do `-es` and `-en` share the same registro oficial?**
**Yes.** For every case tested, both language UIs expose the identical
`nregaud` (registro oficial: 20509, 20875, 20448, 20854, 20515, 20934) and
the identical submission `nreg` (2025031067, 2026029493, 2025022995,
2026023406, 2025031726, 2026031462), the same financial-statement date,
publication date, auditor and `infadicionifa` history page. The `-en` is a
second document set **inside the same registry entry**, not a separate
submission.

**Q3 — can variants have independent dates, substitutions, histories?**
The registry-level metadata (dates, auditor, opinion, additional-info page)
is shared between variants; the row's publication date is defined as "fecha
de remisión del IFA o última sustitución", so any substitution bumps the
single shared date. Whether a variant document can be substituted
independently while its sibling stays is **not observable** in these six
cases — it remains a falsification target if a historical multi-substitution
case is found (the shared `infadicionifa` history would reveal it).

**Q4 — which identifier is stable?**
`nregaud` (registro oficial) is the filing identity; the submission `nreg`
is shared by both variants; `language` selects the artifact set; package
SHA-256 distinguishes variant content. LEI+period identifies the obligation
but not the submission.

## Model implication

All six registros land in the preregistered same-registry outcome, refined
per filing: `DUAL_VARIANT_SHARED_REGISTRY` (SAN, BBVA — two real submitted
variants) and `SINGLE_VARIANT_WITH_UI_FALLBACK` (IBE — one submitted variant;
the `lang=en` view serves the same `-es` bytes). Same registro, same
submission nreg, same publication date, same `infadicionifa` history
surface; where two variants exist they are distinct language artifact sets.

**Important honesty note:** current evidence does **not** distinguish the
lifecycle ordering. The observed shape is still perfectly compatible with
`filing → filing_version → {variant es, variant en}` (both variants inside
one version) and with `filing → {variant es, variant en} → version N`
(variants evolving in sync). What is missing — and what would falsify — is
a substitution affecting one variant but not the other. Until such a case is
observed, the orthogonal representation

```text
filing (identity = nregaud)
  ├─ submission_variant   (language → artifact set)
  └─ version_event        (shared registry-level history)
```

is the **least-assumptive, lossless provisional model** — not an
experimentally falsified conclusion.

## Consequences for OpenCNMV

1. The R16 `OPEN_CNMV_POSSIBLE_OMISSION` is upgraded to a **confirmed,
   explained omission**: the `-en` packages were always discoverable via the
   same official surface with `lang=en`; the G0 corpus captured only the
   `lang=es` view. Coverage of the *selected surfaces* remains exactly what
   G0-R claimed; G1 corpus extension must fetch both language views.
2. The `-en` packages preserved here are official CNMV bytes, sha256-verified;
   SAN-FY2024 `-en` is byte-identical to the oracle's copy
   (`47923b30…` == oracle `sha256` field), confirming the oracle sourced it
   from this surface.
3. SAN-FY2025 `-en` exists at CNMV (`77ac614a…`) although the oracle never
   indexed it — consistent with R16's `ORACLE_OMISSION` (ingest lag).
4. Variants are parallel artifact sets, not translations to merge:
   the BBVA `Equity` −98M/+98M divergence (R16) stands as the reference case
   for `DIVERGENT_SUBMISSION_FACT`.

## Preregistered outcome vocabulary → actual results

| outcome | count |
|---|---|
| DUAL_VARIANT_SHARED_REGISTRY | 4 (SAN FY2024/FY2025, BBVA FY2024/FY2025) |
| SINGLE_VARIANT_WITH_UI_FALLBACK | 2 (IBE FY2024/FY2025) |
| SAME_REGISTRY_INDEPENDENT_VARIANT_VERSIONS | 0 |
| DISTINCT_REGISTRY_SUBMISSIONS | 0 |
| EXTERNAL_ONLY_VARIANT_UNPROVEN_AT_CNMV | 0 |
| UNRESOLVED | 0 (per-variant independent substitution unproven — see Q3) |

## Evidence

- `evidence/busqueda25-{SAN,BBVA,IBE}-{es,en}.html` — raw search-result pages.
- `evidence/esef-{SAN,BBVA}-FY202{4,5}-en.zip` — official `-en` packages
  served by `verdocumento` under `lang=en` (sha256 in `manifest.json`).
- `evidence/resultado-oir-33155.html` — OAM daily-feed detail for SAN FY2024
  IFA (registro 33155 → links to `listadoifa`; no separate `-en` feed entry).
- `g1a_results.json` — full per-row record (cells, tokens, links, shas).
- `g1a_discover.py` — deterministic probe; rerunnable, hash-verified.

## Limitations

- Variant sets per registro were verified via the ZIP package + document
  tokens; the large standalone `-en` XHTML viewers (up to ~100 MB) were
  identified by title/token but not preserved in this probe.
- Per-variant independent substitution history is not observable in the six
  in-scope cases; a historical multi-variant + modification case remains a
  falsification target.
- Coverage claim stays scoped: this proves `-en` discovery on the
  `busqueda?id=25`/`listadoifa` surfaces; other OAM surfaces were not
  exhaustively enumerated.
