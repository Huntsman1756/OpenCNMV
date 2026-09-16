# G2-B — FULL_FROZEN_CORPUS_REBUILD

**Question (preregistered):** can the durable production parser/canonicalizer
rebuild all 25 frozen XBRL states fully offline, with the same semantics as
the evidence that produced canonical model V1?

```text
corpus:
  ESEF variants   10   SAN es/en x FY2024/25, BBVA es/en x FY2024/25,
                       IBE es x FY2024/25
  IPP             15   SAN/BBVA/IBE x H1-2024 H2-2024 H1-2025 H2-2025 H1-2026
  total unique parses = 25
```

**Production path under test** — no gate code:

```text
opencnmv.xbrl.arelle (ParseSession: pinned-version check, one Session per
  filing, offline connectivity, fingerprint-gated base64 shim for IPP,
  SHA-verified .xbrl entrypoint copy for .zip-suffixed IPP instances)
        |
opencnmv.canonicalize.facts (fact_record: full unit num/den, explicit AND
  typed dims, decimals, nil, xml:lang, value_sha256; profiles esef|ipp)
```

Frozen R11/R12/G1-B `facts.jsonl` + `model_summary.json` are regression
**oracles** (read as data, sha-pinned); never imported.

**Runs**

```text
RUN A   PYTHONHASHSEED=17   RUN B   PYTHONHASHSEED=991
both:   fresh Arelle profile/cache — XDG_CONFIG_HOME, HOME/USERPROFILE,
        APPDATA/LOCALAPPDATA, TEMP/TMP redirected to run-local dirs
        socket deny-all + gate-code import blocker inside every worker
```

**Checks (PASS/FAIL)**

```text
B1 input sha verification          all frozen inputs PASS
B2 production parse                25/25 OK, ioerr=0, DTS resolves only from
                                   pinned packages / local inputs
B3 semantic equality vs frozen     facts.jsonl equal after LF normalisation
                                   (oracles were written CRLF on Windows)
                                   AND field multiset equal:
                                   concept, entity scheme+id, period,
                                   explicit+typed dims, FULL unit,
                                   decimals, nil, xml:lang, value_sha256,
                                   contextID, unitID; plus summary counts
B4 typed dimensions                real IPP typed-dim counts == oracle;
                                   synthetic compound-unit selftest
B5 Control A                       API multiset == Arelle OIM multiset, 25/25
B6 offline purity                  0 network attempts; 0 gate-code imports
B7 determinism                     runA facts == runB facts, per filing and
                                   aggregate corpus hash
B8 negative dependency controls    ESEF minus ESMA taxonomy pkg -> FAILS
                                   IPP minus xl/xlink entries -> FAILS
```

**Non-goals:** discovery, variant lifecycle, extension mapping (already
proven in G1); storage/columnar layout (G2-C); any new CNMV access.

Run: `python g2b_rebuild.py` then `python g2b_verify.py`.
