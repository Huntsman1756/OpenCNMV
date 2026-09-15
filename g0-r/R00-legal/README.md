# R0 — LEGAL_REUSE_REVIEW

**Gate:** R0 — LEGAL_REUSE_REVIEW
**Status:** `PASS`
**Executed:** 2026-09-14 (UTC 22:15)

## Purpose

Review the CNMV's legal / reuse conditions for the portal surfaces that OpenCNMV's
G0-R depends on, and decide whether reuse (download, storage, faithful republication,
computation) is legally viable without a written agreement.

## Surfaces reviewed

| Surface | URL | Evidence |
|---|---|---|
| Legal note (aviso legal) | `https://www.cnmv.es/portal/Utilidades/NotaLegal` | `evidence/nota-legal.html` (+ `.txt`), SHA-256 `96C127DD…` |
| Cookies policy | `https://www.cnmv.es/portal/Utilidades/Politica-Cookies` | `evidence/politica-cookies.html` (+ `.txt`), SHA-256 `CEE34A0F…` |
| Robots / technical conditions | `https://www.cnmv.es/robots.txt` | `evidence/robots.txt`, SHA-256 `BEE2023C…` |

## Findings (verbatim key clauses, translated)

### Owner
`www.cnmv.es` is a domain owned by the Comisión Nacional del Mercado de Valores
(CIF Q-2891005-G), Calle Edison n.º 4, Madrid.

### Disclaimer of liability
Information published is informational only. CNMV reserves the right to suspend,
modify or restrict access without notice, does not guarantee continuity, and is not
liable for decisions taken on the basis of the information or for inaccuracies,
omissions or errors. CNMV **is not responsible for the veracity of public information
incorporated into its official registers that was delivered by third parties to comply
with a legal obligation**; registration only implies the acknowledgement that the filing
contains everything required by the applicable rules.

> Consequence for OpenCNMV: the filings are third-party (issuer) documents delivered to
> comply with a legal obligation. CNMV does not vouch for their veracity. This reinforces
> the principle of preserving original bytes and not "correcting" issuer content.

### Intellectual property / reuse conditions (the operative clause)
- © CNMV. Texts, photos and graphics are the exclusive property of CNMV. **In general CNMV
  does not grant a licence of use over its industrial/intellectual property rights, except
  by express written agreement with third parties**, and reserves the right to modify or
  limit the conditions of use of the information published.
- **Free private use is allowed:** users may make free private use of information obtained
  directly from the site, including copying to RAM / temporary local storage.
- For any use **other than mere private consultation**, use is authorised only if these
  conditions are met:
  1. **Distribution or reproduction must be faithful**, without manipulating or altering
     the contents. → aligns with OpenCNMV's immutable-bytes principle.
  2. When information is incorporated into documents that will be **sold or transferred
     for a fee**, the publisher must inform buyers/assignees that the information can be
     obtained free of charge from the CNMV site (both before payment and each time it is
     made available).
  3. The information may be used **for calculations** that the user disseminates
     (e.g. statistical adjustments, evolution-rate calculations). → aligns with OpenCNMV
     derived facts / period_role.
  4. When linking to the CNMV site, pages must open in an **independent window** and be the
     only element on screen (no framing).
- Users must respect these conditions; CNMV reserves legal actions for non-compliance.

## Conclusion / viability for OpenCNMV G0-R

- **Download + local storage + faithful reproduction (immutable bytes):** permitted
  (conditions 1 and free private use).
- **Computation on the facts and dissemination of the results:** permitted (condition 3).
- **Republication of raw filings faithfully (unmodified):** permitted by condition 1, with
  the constraint that reproduction must be faithful. OpenCNMV must therefore ship the exact
  bytes the CNMV serves, and treat any normalised/canonical view as derived data, never as a
  replacement for the raw artifact.
- **Monetised distribution of CNMV-derived documents** would trigger condition 2 (informing
  buyers that the data is free at source). OpenCNMV aims to be open/auditable; this must be
  honoured if any paid distribution is ever added.
- **No framing / independent window** (condition 4) is relevant for any future web UI that
  embeds CNMV pages.

## Limitations / why still a `PASS` with caveats

1. **Third-party rights:** the underlying filings (annual accounts, ESEF/iXBRL, IPP) are
   authored by the issuers and delivered under a legal obligation. CNMV's reuse conditions
   govern *its* site; they do not necessarily authorise reuse of the issuers' underlying
   copyright. This must be tracked for R1+; it does not block a source probe.
2. **Spanish public-sector reuse framework (Ley 37/2007 / open data):** not reviewed in depth
   in this session. CNMV data may additionally be in scope; treated as a follow-up.
3. **Sede electrónica (`sede.cnmv.gob.es`) and the `/IPPS/` application** may carry separate
   terms not captured here; noted for review if those are used as entrypoints.
4. `Política de cookies` confirms third-party Google analytics/advertising cookies on the
   portal, but no cookie is required to fetch the registry/artifact endpoints (see R2/R4).

## Evidence

- `evidence/nota-legal.html` / `evidence/nota-legal.txt`
- `evidence/politica-cookies.html` / `evidence/politica-cookies.txt`
- `evidence/robots.txt`
