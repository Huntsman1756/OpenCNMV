# G1-D — VARIANT_LIFECYCLE_FALSIFICATION

**Verdict: PASS** (11/11 checks, `g1d_verify.py`)

Question: can a `version_event` (Circular 3/2018 substitution) affect only a
**subset** of `submission_variant`, or does a CNMV substitution always replace
the complete submission set?

## Answer: INDEPENDENT_VARIANT_LIFECYCLE_PROVEN

TELEFONICA, S.A. FY2024 (`nregaud` 20484) — a `DUAL_VARIANT_SHARED_REGISTRY`
filing — shows a substitution event scoped **only to the `-en` variant**.

## Evidence

### Candidate discovery

`g1d_scan.py` (37-issuer FY2025 watchlist) + `g1d_scan2.py` (96 filings,
FY2023–FY2025, same mechanism): 12 dual-variant filings, 8 filings with
substitution rows — **one intersection**: TEF-20484. Other substitution
candidates (AMPER 20938, BANKINTER 20860, URBAR 21257) classify
`SINGLE_VARIANT_WITH_UI_FALLBACK` — same ZIP token/bytes under both UI
languages — so they cannot falsify variant lifecycle.

Methodology caveat: scan detection counted rows whose event label contains
"sustitución". TEF-20484's decisive event is labelled *"Otra información
complementaria (Otros)"* — its **document content** is a substitution
certificate. Label-based detection is a lower bound only; document content
is authoritative.

### TEF-20484 timeline (one registry, three submissions)

| nreg | submitted | event | scope |
|---|---|---|---|
| 2025030764 | 2025-02-27 | original FEUE submission | — |
| 2025031622 | 2025-02-28 | substitution: adds audit report, declaration of responsibility and signature sheet to the *Cuentas Anuales Individuales* | `VARIANT_SCOPE_NOT_OBSERVABLE` |
| — | 2025-03-13 | substitution: *"la versión en inglés publicada de los Estados Financieros Consolidados … aparece en español"* | **`EN_ONLY_REPLACED`** |

The 2025-03-13 certificate (preserved `doc-TEF-20484-es-e1-0.pdf`, sha256
`e66a65e3…`, served byte-identical under both UI languages) states the second
substitution replaced the submission whose published **English** consolidated
statements appeared in Spanish. Current state is consistent: the `-en`
consolidated viewer now serves English content (`lang=en`).

### Scope rule (preregistered)

`BOTH_VARIANTS_REPLACED` is never inferred from shared registry/date. The
2025-02-28 event stays `VARIANT_SCOPE_NOT_OBSERVABLE`: its reason clause
identifies the *individual accounts* but is silent on language. The
2025-03-13 event is `EN_ONLY_REPLACED` on explicit source text.

### What the shared event log does and does not show

Both UI languages expose the same `infadicionifa` history with
byte-identical certificate documents — the event log is shared, but the
*artefact scope* of the 2025-03-13 event was `-en` only. A `version_event`
can therefore affect a subset of `submission_variant`.

## Model implication

```text
variant → versions        gains strong evidence (en-only replacement observed)
version → {variants}      not falsified in general (a synchronized replacement
                          could still occur), but cannot be the only topology
```

`submission_variant` and `version_event` must remain separately modelled; a
version event needs an explicit `affected_variants`/artefact-set scope.

## Checks (`g1d_verify.py` — 11/11 PASS)

1. TEF-20484 dual-variant: distinct package sha256, root tags `es`/`en`.
2. Both variant packages preserved on disk, sha-verified.
3. EN_ONLY event: decisive clause present in preserved cert text + scope.
4. 28/02 event stays `VARIANT_SCOPE_NOT_OBSERVABLE` (no language scope).
5. Event docs byte-identical across UI languages (shared history).
6. Scope vocabulary limited to the four preregistered classes; no inferred BOTH.
7. Filing verdict `INDEPENDENT_VARIANT_LIFECYCLE_PROVEN`.
8. Other substitution candidates all `SINGLE_VARIANT_WITH_UI_FALLBACK`.
9. PDF text extraction deterministic (re-extract == preserved `.txt`).
10. `g1d_results.json` rebuild byte-identical.
11. All manifest artifacts preserved with matching sha256.

## Reproduce

```bash
python g1d_probe.py        # FY2025 candidates capture (AMPER/BANKINTER/URBAR)
python g1d_scan.py         # FY2025 watchlist scan
python g1d_scan2.py        # wide FY2023-25 scan -> dual+substitution hits
python g1d_tef_capture.py  # full TEF-20484 capture (packages, certs, signals)
python g1d_results.py      # consolidated dataset -> g1d_results.json
python g1d_verify.py       # 11 checks
```

## Limitations

- CNMV serves only current state: whether the `-en` ZIP bytes changed on
  2025-03-13 is not observable (served `-en` package retains 27/02 internal
  zip timestamps — consistent with the replaced artefact being the published
  consolidated XHTML document rather than a rebuilt package).
- `EN_ONLY_REPLACED` proves independence for this filing; it does not prove
  CNMV always permits partial-variant replacement.
- Substitution detection was label-based in the scans; the decisive TEF event
  was labelled "otros" — other en/es-only substitutions may exist undetected.
