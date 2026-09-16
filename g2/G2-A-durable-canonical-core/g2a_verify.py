# G2-A verifier — production core rebuilds the frozen V1 fixtures.
#
#   A1  run1 == frozen G1-E fixtures, byte-identical (4/4)
#   A2  production objects validate against the frozen JSON Schema and the
#       production pydantic model
#   A3  src/opencnmv contains no imports from g0-r/ or g1/ code
#   A4  rebuild ran under guards: socket deny-all, gate-code import blocker,
#       pinned evidence inputs, 0 network calls attempted
#   A5  run1 == run2 (deterministic rebuild)
#   A6  semantic spot-checks on production objects (IBE fallback, BBVA
#       divergence, SAN PROVEN-only, TEF variant-scoped lifecycle)
from __future__ import annotations

import json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIX = ROOT / "g1/G1-E-canonical-model-freeze/fixtures"
SCHEMA = ROOT / ("g1/G1-E-canonical-model-freeze/"
                 "canonical_model_v1.schema.json")
OUT = HERE / "_out"
SRC = ROOT / "src" / "opencnmv"

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "status": "PASS" if ok else "FAIL",
                   "detail": detail})
    print(("PASS " if ok else "FAIL "), name,
          ("| " + detail) if detail else "")
    return ok


def main():
    import jsonschema

    for run in ("run1", "run2"):
        subprocess.run([sys.executable, "-X", "utf8",
                        str(HERE / "g2a_rebuild.py"), str(OUT / run)],
                       check=True, capture_output=True)

    frozen = {p.name: p.read_bytes() for p in sorted(FIX.glob("*.json"))}
    r1 = {p.name: p.read_bytes()
          for p in sorted((OUT / "run1").glob("*.json"))
          if not p.name.startswith("_")}
    r2 = {p.name: p.read_bytes()
          for p in sorted((OUT / "run2").glob("*.json"))
          if not p.name.startswith("_")}

    check("A1_byte_identical_to_frozen_fixtures",
          r1 == frozen and len(r1) == 4,
          f"{sorted(r1)} == frozen")
    check("A5_rebuild_deterministic", r1 == r2)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    ok = True
    models = {}
    sys.path.insert(0, str(ROOT / "src"))
    from opencnmv.model.canonical import CanonicalFiling
    for n, b in r1.items():
        fx = json.loads(b)
        try:
            jsonschema.validate(fx, schema)
            models[n] = CanonicalFiling.model_validate(fx)
        except Exception as ex:  # noqa: BLE001
            ok = False
            print("  schema/model fail:", n, str(ex)[:120])
    check("A2_conformance_frozen_schema_and_model", ok)

    bad = []
    for p in SRC.rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8")
                                 .splitlines(), 1):
            if re.match(r"\s*(from|import)\s+(g0_r|g0-r|g1)[\.\s]",
                        line):
                bad.append(f"{p.name}:{i}:{line.strip()}")
    check("A3_no_gate_code_imports", not bad,
          str(bad) if bad else f"{len(list(SRC.rglob('*.py')))} modules clean")

    prov = json.loads((OUT / "run1" / "_provenance.json")
                      .read_text(encoding="utf-8"))
    pins = json.loads((HERE / "g2a_inputs.json").read_text(encoding="utf-8"))
    check("A4_guards_and_pinned_inputs",
          prov["guards"]["socket_denied"]
          and prov["guards"]["gate_code_imports_blocked"]
          and prov["guards"]["network_calls_attempted"] == 0
          and prov["inputs"] == pins)

    tef = models["tef_20484.json"]
    env = next(v for v in tef.submission_variants
               if v.variant_id.endswith("#en"))
    esv = next(v for v in tef.submission_variants
               if v.variant_id.endswith("#es"))
    ev13 = next(e for e in tef.version_events
                if e.event_id.endswith("2025-03-13"))
    ev28 = next(e for e in tef.version_events
                if e.event_id.endswith("2025-02-28"))
    ibe = models["ibe_fy2024.json"]
    bbva = models["bbva_fy2024.json"]
    ok6 = (
        len(ibe.submission_variants) == 1
        and any(v.resolution_mode.value == "FALLBACK_TO_ES"
                for v in ibe.view_resolutions)
        and bbva.fact_examples[0]["en"]["value"] == "-98000000"
        and len(env.variant_versions) == 2
        and len(esv.variant_versions) == 1
        and env.variant_versions[0].observed is False
        and ev13.source_nreg is None
        and ev13.affects[0].variant_id == env.variant_id
        and ev28.scope_status.value == "VARIANT_SCOPE_NOT_OBSERVABLE")
    check("A6_semantic_spot_checks", ok6,
          "IBE fallback / BBVA -98M / TEF en v1->v2, nreg null, "
          "28/02 NOT_OBSERVABLE")

    n_pass = sum(1 for c in CHECKS if c["status"] == "PASS")
    verdict = "PASS" if n_pass == len(CHECKS) else "FAIL"
    print(f"\nG2-A: {verdict} ({n_pass}/{len(CHECKS)})")
    (HERE / "g2a_verify_results.json").write_bytes(json.dumps(
        {"verdict": verdict, "checks": CHECKS},
        indent=1, ensure_ascii=False).encode("utf-8"))
    return verdict == "PASS"


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
