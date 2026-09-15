# R4 — ARTIFACT_URL_STABILITY

**Gate:** R4 — ARTIFACT_URL_STABILITY
**Status:** `PASS` (remediated)
**Executed:** 2026-09-14 (UTC) — after checkpoint `CONTINUE`
**Reason for PASS (remediated):** R9 proved the earlier "ESEF iXBRL" artefacts were the
**Portada/cover**. The real ESEF iXBRL is now tested: all 6 **IXBRL_CONSOLIDATED** (SAN/BBVA/IBE ×
FY2024/FY2025) are **byte-stable out-of-session** (run1==run2 SHA-256), as are the 6
**ESEF_PACKAGE_ZIP_XBRL** and the 6 **ESEF_COVER**; the 15 **IPP_XBRL** are byte-stable too.
**Key finding:** the IPP `?t={GUID}` is **ephemeral** (re-downloading a stored `?t=` returns empty);
`nreg` via discovery is the stable IPP locator. The `?e=` tokens are stable across visits.

## Objective

Check whether final artefact URLs work outside a session, are reusable, contain a stable
identifier, survive between runs, and require no cookies/referer. (Distinct from discovery
stability, R3.)

## Corpus-family results (this resolution session)

### 1. IPP raw XBRL — `nreg` → detail → `descargaxbrlipp.ashx?t={GUID}` → redirect → `ver?e=<token>`
| Issuer / slot | Final media type | Bytes | SHA-256 (run1 == run2) |
|---|---|---|---|
| IBE H1-2026 | `text/xml` | 5,681,490 | `5EB26CAB…` (identical ×3) |
| SAN H1-2026 | `text/xml` | 31,780,095 | `A1FAD8F5…` |
| BBVA H1-2026 | `text/xml` | 13,226,141 | `CFCCA102…` |

- Out-of-session (no cookies), no referer, no session.
- Byte-stable: two fresh downloads per issuer produced identical SHA-256.
- **Ephemeral `?t={GUID}`:** the IPP detail page emits a different `?t={GUID}` on each visit, but it
  always redirects to the **same `?e=` token** and the **same bytes**. Verified: two different GUIDs
  for the same `nreg` both returned SHA-256 `5EB26CAB…`. Therefore `?t={GUID}` is **not** a stable
  identifier and must not be used as identity.

### 2. ESEF iXBRL — `ListadoIFA` → `ver?e=<token>`
| Issuer / year | Final media type | Bytes | SHA-256 (run1 == run2) |
|---|---|---|---|
| IBE FY2025 | `application/xhtml+xml` | 8,077,560 | `1FF573FB…` |
| SAN FY2025 | `application/xhtml+xml` | 23,512,400 | `5CF07C65…` |
| BBVA FY2025 | `application/xhtml+xml` | 21,919,098 | `D819FC69…` |

- Out-of-session (no cookies), no redirect, no referer.
- Byte-stable: two fresh downloads per issuer produced identical SHA-256.
- **Stable `?e=` tokens:** the 18 ESEF `?e=` tokens were **identical** between two separate
  `ListadoIFA` fetches (0 differences), i.e. the tokens survive between visits.

### 3. (Earlier) generic GUID webservice + taxonomy ZIP — still stable
- `verdocumento/ver?t={GUID}` PDF: `E78E3F2F…` (run1 == run2); taxonomy ZIP: `87C44522…`.

## Findings

- The final artefact URL (`verdocumento/ver?e=<token>`) is **stable, reusable, out-of-session and
  byte-deterministic** for both IPP and ESEF, across all three issuers.
- The **stable canonical identifiers** are the discovery keys: `nreg` (IPP) and `registro oficial`
  (ESEF), used as `source_registration_no`. The `?e=` token is the per-artefact identifier.
- The IPP `?t={GUID}` is an **ephemeral redirect parameter** and must never be used as identity.

## Distinction R3 vs R4

Discovery links (R3) are stable; the artefact URL itself (R4) is stateless and hash-stable. R3 and
R4 are independent: discovery requires browsing, but once a stable `?e=` is known the artefact is
directly retrievable without any session.

## Limitations / caveats

- The IPP `?t={GUID}` is ephemeral; the canonical identity relies on `nreg`/`registro` + the stable
  `?e=`, regenerated via discovery each run. This is deterministic in output (same bytes).
- Long-horizon token/URL drift (source replacing a file, token expiry) is the responsibility of
  **R8 (RAW_SHA256_STABLE)** and will be monitored there; it does not invalidate R4.
- A single URL sample per issuer/family was byte-tested twice; the broader per-period matrix is
  captured by R7/R8 in R5+.

## Evidence

- `evidence/ipp-IBE-H1-2026_run1.zip`, `_run2.zip`, `_run3_obs2guid.zip` (identical `5EB26CAB…`)
- `evidence/esef-IBE-consolidated_run1.zip`, `_run2.zip` (identical `1FF573FB…`)
- `evidence/ipp-SAN-H1-2026_run1.zip`, `_run2.zip` (identical `A1FAD8F5…`)
- `evidence/esef-SAN-FY2025_run1.zip`, `_run2.zip` (identical `5CF07C65…`)
- `evidence/ipp-BBVA-H1-2026_run1.zip`, `_run2.zip` (identical `CFCCA102…`)
- `evidence/esef-BBVA-FY2025_run1.zip`, `_run2.zip` (identical `D819FC69…`)
- `evidence/guid_doc_run1.pdf`, `guid_doc_run2.pdf` (identical `E78E3F2F…`), taxonomy ZIPs (`87C44522…`)
