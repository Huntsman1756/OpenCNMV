# R4 — ARTIFACT_URL_STABILITY

**Gate:** R4 — ARTIFACT_URL_STABILITY
**Status:** `FAIL`
**Executed:** 2026-09-14 (UTC 22:15)
**Reason for FAIL:** Stability was proven only for one generic GUID artefact (a press/regulatory
PDF) and one taxonomy ZIP, **not** for the two real corpus families (ESEF iXBRL and IPP XBRL).
The ESEF consolidated iXBRL reportedly serves via `webservices/verdocumento/ver?e=<opaque-token>`,
a variant not tested here. Per project rules there is no `mostly-pass`; until both target
families are proven out-of-session and across observations, R4 is `FAIL`.

## Objective

Check whether final artefact URLs work outside a session, are reusable, contain a stable
identifier, survive between runs, and require no cookies/referer. (Distinct from discovery
stability, R3.)

## Targets tested

### 1. Raw-artefact webservice (GUID-keyed) — `DIRECT_URL`
URL: `https://www.cnmv.es/webservices/verdocumento/ver?t=%7b<guid>%7d`
(example GUID `b20b74da-e03d-4cd7-a8a3-0787d078dc0e`)

| Run | Status | Final URL | Media type | Bytes | SHA-256 |
|---|---|---|---|---|---|
| run1 | 200 | unchanged (no redirect) | `application/pdf` | 291225 | `E78E3F2F…` |
| run2 | 200 | unchanged (no redirect) | `application/pdf` | 291225 | `E78E3F2F…` |

- **Out-of-session:** works with **no cookies** (`SET_COOKIE: (none)`), no Referer, no session.
- **No redirect:** final URL equals requested URL (no `.aspx` rewrite involved).
- **Stable identifier:** the GUID is the identifier; it is stable between runs.
- **Byte-stable:** two independent fresh downloads produced an **identical SHA-256**.

### 2. Static taxonomy ZIP — `DIRECT_URL`
URL: `https://www.cnmv.es/IPP/taxonomia/2019-01-01/ipp_2019-01-01.zip`

| Run | Status | Media type | Bytes | SHA-256 |
|---|---|---|---|---|
| run1 | 200 | `application/x-zip-compressed` | 357340 | `87C44522…` |
| run2 | 200 | `application/x-zip-compressed` | 357340 | `87C44522…` |

- Direct static file, no redirect, no cookies, byte-stable (identical SHA-256).

## Findings

- The `verdocumento/ver?t={GUID}` webservice and the static taxonomy ZIP are **stable, reusable,
  out-of-session, and byte-deterministic** — good evidence for the immutable-bytes / SHA-256
  model **for those two specific artefacts**.
- The GUID in `verdocumento/ver?t=` is a **stable source identifier** (candidate for
  `source_filing_key` / `source_registration_no` in the filing_version model).
- Static taxonomy paths are versioned and stable, which supports R9/R10 taxonomy pinning.

## Distinction R3 vs R4

Discovery links (R3) are stable; the artefact URL itself (R4) is stateless and hash-stable.
The two are independent: discovery requires browsing, but once a GUID is known the artefact is
directly retrievable without any session.

## Limitations (the reason for FAIL)

- **Not the target families.** Only one generic GUID artefact (a press/regulatory PDF) and one
  taxonomy ZIP were hash-tested. The two real corpus families — **ESEF iXBRL** (via
  `ListadoIFA?nif=` → `registro oficial` → individual/consolidado) and **IPP XBRL** (via
  `listaifi?nif=` → `nreg` → `detalleifialdia` → `descargaxbrlipp.ashx?t={GUID}`) — were **not**
  tested out-of-session.
- **`?e=` variant.** The ESEF consolidated iXBRL reportedly serves via
  `webservices/verdocumento/ver?e=<opaque-token>` — a **different** parameter than the tested
  `?t={GUID}`. This variant needs its own out-of-session and cross-observation test.
- **URL-identity caveat.** If `?e=<token>` changes on every visit while still returning the same
  bytes, R4 **must remain FAIL**: the canonical identity cannot rest on the URL, and the
  downloader must regenerate the URL via discovery. We must not move the threshold to manufacture
  a PASS.
- Hash stability was observed within one session window (~20 min); longer-horizon drift (source
  replacing a file) is exactly what R8 is designed to catch later.

## Evidence

- `evidence/guid_doc_run1.pdf`, `evidence/guid_doc_run2.pdf` (identical SHA-256 `E78E3F2F…`)
- `evidence/ipp_2019-01-01_run1.zip`, `evidence/ipp_2019-01-01_run2.zip` (identical SHA-256 `87C44522…`)
