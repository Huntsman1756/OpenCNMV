# G2-A — DURABLE_CANONICAL_CORE

**Verdict: PASS** (6/6 checks, `g2a_verify.py`)

The durable core (`src/opencnmv/`) rebuilds the four frozen G1-E fixtures
from sha256-pinned preserved evidence — **byte-identical**, offline, with
zero imports from gate code (`g0-r/`, `g1/`).

## What the production core provides

```text
src/opencnmv/
  model/canonical.py      V1-conformant pydantic objects
  model/ids.py            deterministic id constructors
  source/cnmv/            discovery.py + retrieval.py (official surfaces)
  xbrl/arelle.py          thin offline Arelle 2.44.0 adapter
  xbrl/taxonomy.py        package lang tag + extension ns detection
  canonicalize/           filing / variants / facts / events /
                          extension_mapping assembly (V1 layout)
  provenance/             hashes.py (artifact_set_id), manifests.py
  serialize.py            deterministic canonical JSON (LF bytes)
```

`xbrl/arelle.py` is the parser adapter for G2-B (full corpus rebuild); it
is not exercised by the fixture test since fixtures carry extracted fact
evidence, not XBRL re-parses.

## Checks

| check | assertion |
|---|---|
| A1 | run1 output byte-identical to the 4 frozen fixtures |
| A2 | objects validate vs frozen JSON Schema + production model |
| A3 | no `g0-r`/`g1` imports anywhere under `src/opencnmv` |
| A4 | rebuild under socket deny-all + gate-code import blocker + pinned inputs, 0 network calls |
| A5 | run1 == run2 (deterministic) |
| A6 | semantic spots: IBE fallback, BBVA −98M, SAN PROVEN-only, TEF en v1→v2 / nreg null / 28-02 NOT_OBSERVABLE |

## Contract rule

The frozen V1 schema is the contract. The production model must conform;
any incompatible change requires an explicit `CANONICAL_MODEL_V2`.

## Reproduce

```bash
python g2a_rebuild.py _out/run1   # offline rebuild, pinned inputs
python g2a_verify.py              # 6 checks
```
