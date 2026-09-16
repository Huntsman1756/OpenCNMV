# R15 — OFFLINE_REBUILD_DETERMINISTIC

**Gate:** R15 — OFFLINE_REBUILD_DETERMINISTIC (critical)
**Status:** `PASS`
**Executed:** 2026-09-16 (UTC)

## Objective

Per `docs/gates/G0-R.md`: run with network denied. Allowed inputs: raw artefacts,
pinned taxonomy packages, exact Arelle version, configuration, canonicalizer code,
manifests. Must produce exactly the same semantic artefacts. If it needs Internet →
FAIL.

## Design

**Zero discovery.** The rebuild never touches `listaifi`, `ListadoIFA`, `?e=`,
`?t={GUID}`, CNMV, ESMA, xbrl.org or GLEIF. It starts from a closed local input set
whose sha256 is verified against the frozen manifests **before any processing**
(60 inputs: 27 raw artefacts, R10 taxonomy packages incl. derived packages, R13
preserved pages for offline event re-derivation, harness/canonicalizer code
identity). Any mismatch aborts the run.

**Defense in depth (network denial):**

```text
preflight unguarded:  cnmv.es / xbrl.org / esma.europa.eu -> REACHABLE
                      (host connectivity exists; denial is proven, not assumed)
socket deny-all sentinel: socket.connect / connect_ex / create_connection /
                      getaddrinfo all raise R15-NETWORK-DENIED + are logged
preflight guarded:    all three -> DENIED (sentinel) — block verified
Arelle:               internetConnectivity="offline" (R11/R12 harness code)
Arelle caches:        empty — TMP/TEMP + USERPROFILE/APPDATA/LOCALAPPDATA/HOME
                      all redirected into the run root
proxy env:            HTTP(S)_PROXY = 127.0.0.1:9 (dead) as an extra layer
read audit:           builtins.open hooked; reads outside repo/run-root/
                      interpreter/C:\Windows are flagged
```

No OS firewall rule was added (requires elevation); the denial is enforced at
process level inside the rebuild, which spawns no children. This is stated
honestly rather than claimed as an OS-level block.

**Two offline rebuilds:**

```text
OFFLINE A   clean temp root, empty caches/profile   PYTHONHASHSEED=11
OFFLINE B   same                                     PYTHONHASHSEED=999
```

**Triple binding:** `offline_A == offline_B` on every level, `offline_A == R14`
canonical projections (levels derivable from the frozen bundle: artifact manifest,
taxonomy selection, events, fact inventory, source_state — the discovery
projection is *not* rebuilt, by design), `offline_A facts == committed R11/R12`
evidence.

**Dependency starvation controls** (prove the closed set is load-bearing):

- `starve-esef`: SAN-FY2025 with `esef_taxonomy_2024.zip` removed → MUST FAIL.
- `starve-ipp-xl`: SAN-H1-2024 with `xl-2003-12-31.xsd` removed from the derived
  IPP package → MUST FAIL.

## Results

```text
network_block_verified                  PASS  (unguarded REACHABLE → guarded DENIED)
external_connect_attempts_after_guard   0
unapproved_file_reads                   0
input_verification                      60/60 inputs, 0 mismatches
Arelle user cache/profile               empty per run

21/21 filings parsed                    PASS
ioerr                                   0
Control A (API vs OIM)                  multiset-equal 21/21

offline_A == offline_B                  all levels equal
offline_A == R14 projections            artifact_manifest/taxonomy/events/
                                        facts_index/source_state all equal
offline_A facts == R11/R12 committed    21/21 byte-identical

shim version+fingerprint gate           PASS (ran at import; would abort on change)
shim self-test                          PASS
IPP temp .xbrl byte-equivalence         PASS (sha256 asserted per filing)

starve-esef   FAILED_AS_EXPECTED  (IOerror x3, 327 xbrl.5.2.4.2.1 unresolved
                                    concept errors — broken DTS, explicit)
starve-ipp-xl FAILED_AS_EXPECTED  (IOerror + 181 xmlSchema errors; the pinned
                                    member is load-bearing, no silent rescue)

R15 OFFLINE_REBUILD_DETERMINISTIC = PASS
```

## Findings

1. The closed frozen bundle (27 raw artefacts + pinned/derived taxonomy packages +
   manifests + Arelle 2.44.0 + gated shim + harness code) rebuilds the complete
   semantic dataset with **zero network access and zero machine-local state** —
   the central claim of G0-R.
2. The file-read audit caught a real hidden touch: Arelle reads
   `%LOCALAPPDATA%\Arelle\plugins.json` even with `TMP` redirected. Fixed by
   redirecting the whole user profile into the run root; final runs show 0
   unapproved reads.
3. Removing a leaf dependency (`xl-2003-12-31.xsd`) from the derived IPP package
   breaks the DTS with explicit errors — no silent fallback rescued it. Removing
   the ESMA 2024 package produces `IOerror` + unresolved-concept errors. The
   pinned set is genuinely load-bearing.
4. Events are re-derivable offline from preserved `infadicionifa` pages —
   byte-identical to R14's online-observed projection (events hash equal).
5. Two canonicalization subtleties found while binding to R14: `media_type`
   stored as bare MediaType (R7) vs full Content-Type (R14), and percent-escape
   case in `?e=` URLs — both normalized in the comparator, documented, not data
   drift.

## Limitations

- Network denial is process-level (socket sentinel + dead proxy + Arelle offline +
  empty caches), not an OS firewall rule — no elevated rights were used. Any
  outbound attempt would have been logged and raised; none occurred.
- The read audit intercepts Python `open()` only; C-level readers (e.g. libxml2)
  are not instrumented. The read-path coverage claim is therefore partial by
  construction and stated as such.
- Determinism proven on the frozen corpus + this interpreter/dependency set;
  the shim aborts loudly if Arelle or the upstream pattern changes.
- The discovery level is intentionally not rebuilt offline — R14's `source_state`
  is the provenance reference, not an offline-recalculable artefact.

## Evidence

- `r15_rebuild.py` — single offline rebuild (input verification, guards, parse)
- `r15_compare.py` — orchestrator/comparator (2 rebuilds + 2 starvation runs)
- `evidence/offline{A,B}/*.json` — canonical projections + run results
- `evidence/starvation_S{1,2}.json` — dependency-starvation outcomes
- `evidence/r15_results.json` — level hashes, triple binding, acceptance matrix
- `_runs/` — run roots (gitignored); parse outputs, isolated caches/profiles
