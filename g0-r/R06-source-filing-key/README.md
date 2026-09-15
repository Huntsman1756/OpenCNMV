# R6 — SOURCE_FILING_KEY_STABLE

**Gate:** R6 — SOURCE_FILING_KEY_STABLE
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`

## Objective

Find the best available source key, prefer official published identifiers over hashes/synthetic
keys, and **attempt to falsify** the observed hierarchy (IPP=`nreg`, ESEF=`registro oficial`),
especially for substitutions/revisions. Determine whether the key identifies the logical filing, a
specific version, or just a registration record.

## Candidate hierarchy (hypothesis, to be falsified)

```text
IPP  canonical source identity = nreg
ESEF canonical source identity = registro oficial
artifact locator              = webservices/verdocumento/ver?e=<token>   (stable)
ephemeral transport locator   = descargaxbrlipp.ashx?t={GUID}            (never identity)
```

## Falsification attempts

1. **Uniqueness/stability of `nreg` / `registro oficial`.**
   - Each `listaifi` row carries exactly one `nreg` (a date link to `detalleifialdia.aspx?nreg=`).
   - Each `ListadoIFA` row carries one `registro oficial`.
   - Within the corpus (SAN/BBVA/IBE), each period maps to one `nreg` (IPP) / one `registro`
     (ESEF); keys are unique and stable across the two observations.

2. **Individual vs consolidated.** The IPP row is labelled "… individual y consolidado" under a
   single `nreg`, and the ESEF "Tipo Fichero ZIP/Xbrl" cell is "Individual / Consolidada". The
   period is the logical filing; `nreg`/`registro` point to the submission.

3. **Substitution / revision hunt.** Searched all SAN/BBVA/IBE `ListadoIFA` rows and the
   `listaifi` + `detalleifialdia` pages for substitution markers (`sustitu`, `revis`, `correcci`,
   `amended`, `reemplaz`, `rectific`).
   - **Result:** no substitution/revision marker appears in the corpus rows; the "Ampliación
     información" column (col 4) is empty for every corpus row; all appear to be clean initial
     submissions. So no in-corpus substitution was available to directly observe.

4. **Source-documented substitution semantics.** The `ListadoIFA` footnote/legend states:
   - col (1) "Fecha de publicación" = date the issuer submitted the IFA **or, where applicable, the
     date of the last substitution to the initial submission**;
   - col (4) "Ampliación información" covers "modificación de ficheros **sin reformulación**,
     corrigiendo el etiquetado".

   This is the decisive evidence: **the `registro oficial` persists across substitutions** (only the
   date and the underlying `?e=`/file change). A substitution is a **version** of the same logical
   filing, not a new filing.

## Conclusion (hierarchy NOT falsified; confirmed as best observed)

- `nreg` (IPP) and `registro oficial` (ESEF) are stable, unique, official registration keys.
- They are the **best observed `source_registration_no`**: unique + stable across repeated
  observations within the frozen corpus. They identify the **logical filing** (the period/IFA),
  not the issuer and not a single byte set.
- **Stability across a real substitution = NOT_YET_PROVEN.** No substitution was observed in the
  corpus; the semantics that a substitution becomes a new version within the same `registro`/`nreg`
  (changing `?e=` and `fecha de publicación`) is inferred from the source legend, not observed.
  This is **deferred to R13** and must not be inherited as fact by R13.
- `?e=<token>` is a **per-version artefact locator** (not a logical identity).
- `?t={GUID}` is an **ephemeral transport locator** (never identity).
- **Model implication:** `source_registration_no` = `nreg`/`registro oficial` (→ `filing`); the
  `?e=` token + `fecha` (→ `filing_version`). This matches the required filing / filing_version
  split, with substitution-persistence to be verified in R13.

## Limitation

The substitution semantics come from the **source's own documentation** (legend) plus the absence
of any in-corpus substitution, not from a directly-observed substitution. A real substitution case
(if/when one appears in the corpus) should be re-tested against the same hierarchy. This is the
honest boundary of what could be falsified in this pass.

## Evidence

- `g0-r/R01-discovery/evidence/ListadoIFA-{IBE,SAN,BBVA}.html` (rows + legend footnote)
- `g0-r/R01-discovery/evidence/listaifi-{IBE,SAN,BBVA}.html` (per-period `nreg`)
- `g0-r/R01-discovery/evidence/detalleifialdia-{IBE,SAN,BBVA}-H1-2026.html` (detail → `?t={GUID}`)
