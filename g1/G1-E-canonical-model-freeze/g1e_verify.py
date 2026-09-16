# G1-E verifier — freezes the canonical model by testing invariants I1-I9
# over the serialized fixtures, all reconstructed from preserved G1 evidence.
from __future__ import annotations

import hashlib, json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from canonical_model import CanonicalFiling  # noqa: E402

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "status": "PASS" if ok else "FAIL",
                   "detail": detail})
    print(("PASS " if ok else "FAIL "), name,
          ("| " + detail) if detail else "")
    return ok


def load(name):
    fx = json.loads((HERE / "fixtures" / f"{name}.json")
                    .read_text(encoding="utf-8"))
    return fx, CanonicalFiling.model_validate(fx)


def main():
    import jsonschema
    schema = json.loads((HERE / "canonical_model_v1.schema.json")
                        .read_text(encoding="utf-8"))
    ibe, ibe_m = load("ibe_fy2024")
    bbva, bbva_m = load("bbva_fy2024")
    san, san_m = load("san_fy2024")
    tef, tef_m = load("tef_20484")

    # ---- fixtures validate against exported JSON Schema ----------------
    ok = True
    for name, fx in (("ibe", ibe), ("bbva", bbva), ("san", san),
                     ("tef", tef)):
        try:
            jsonschema.validate(fx, schema)
        except Exception as ex:  # noqa: BLE001
            ok = False
            print("  schema fail:", name, str(ex)[:120])
    check("fixtures_validate_against_json_schema", ok)

    # ---- I1: UI language != submission variant --------------------------
    check("I1_ui_language_ne_variant",
          len(ibe["submission_variants"]) == 1
          and len(ibe["view_resolutions"]) == 2
          and any(v["requested_ui_language"] == "en"
                  and v["resolution_mode"] == "FALLBACK_TO_ES"
                  and v["resolved_variant_id"].endswith("#es")
                  for v in ibe["view_resolutions"]),
          "IBE: en view resolves to #es, 1 variant only")

    # ---- I2: variant identity stable, != content hash -------------------
    check("I2_variant_id_not_content_hash",
          all(not v["variant_id"].startswith("sha256:")
              and "#v" not in v["variant_id"]
              for f in (ibe, bbva, san, tef)
              for v in f["submission_variants"]),
          "variant_id = filing#lang; no content hash")

    # ---- I3: variant_version identity == content state ------------------
    check("I3_variant_version_is_content_state",
          all(vv["observed"] == bool(vv["artifact_set_id"])
              for f in (ibe, bbva, san, tef)
              for v in f["submission_variants"]
              for vv in v["variant_versions"]),
          "observed <=> artifact_set_id present")

    # ---- I4: no silent merge / no designated truth ----------------------
    forbidden = {"primary", "truth", "preferred", "canonical_variant",
                 "authoritative_variant", "is_primary", "is_canonical",
                 "main_variant", "default_variant"}

    def field_names(node):
        out = set()
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("properties", "$defs"):
                    out |= set(v.keys()) if isinstance(v, dict) else set()
                out |= field_names(v)
        elif isinstance(node, list):
            for v in node:
                out |= field_names(v)
        return out

    schema_fields = field_names(schema)
    schema_bad = schema_fields & forbidden
    fixture_bad = [k for f in (ibe, bbva, san, tef)
                   for k in field_names(f) & forbidden]
    check("I4_no_truth_designation",
          not schema_bad and not fixture_bad,
          f"schema keys clean ({len(schema_fields)} inspected); "
          f"fixture fields clean; forbidden={sorted(schema_bad | set(fixture_bad)) or 'none'}")

    # ---- I5: fact identity != payload (BBVA divergent pair) -------------
    ex = bbva["fact_examples"][0]
    check("I5_divergent_fact_preserved",
          ex["comparison_class"] == "DIVERGENT_SUBMISSION_FACT"
          and ex["es"]["value"] == "98000000"
          and ex["en"]["value"] == "-98000000"
          and ex["es"]["variant_version_id"] != ex["en"]["variant_version_id"],
          "Equity +98M/-98M on distinct variant_versions, one filing")

    # ---- I6: no concept+period dedup ------------------------------------
    k = ex["key"]
    check("I6_structural_key_full",
          all(f_ in k for f_ in
              ("concept", "entity", "period", "dimensions", "unit"))
          and len(k["dimensions"]) >= 1,
          "dims+entity+unit are part of identity")

    # ---- I7: event scope granularity + nullable nreg --------------------
    ev13 = next(e for e in tef["version_events"]
                if e["event_id"].endswith("2025-03-13"))
    check("I7_event_scope_below_variant_and_null_nreg",
          ev13["source_nreg"] is None
          and ev13["affects"][0]["variant_id"].endswith("#en")
          and ev13["affects"][0]["affected_component_scope"]
          == "SOURCE_DESCRIBED",
          "13/03 event: en variant, component SOURCE_DESCRIBED, nreg null")

    # ---- I8: shared registry/date never implies BOTH --------------------
    ev28 = next(e for e in tef["version_events"]
                if e["event_id"].endswith("2025-02-28"))
    check("I8_no_inferred_both",
          ev28["scope_status"] == "VARIANT_SCOPE_NOT_OBSERVABLE"
          and not any(e["scope_status"] == "BOTH_VARIANTS_REPLACED"
                      for e in tef["version_events"]),
          "28/02 event stays NOT_OBSERVABLE")

    # ---- I9: only PROVEN mappings rewrite identity ----------------------
    non_proven = sum(v for k, v in san["extension_mapping_summary"].items()
                     if k != "PROVEN_EQUIVALENT")
    check("I9_only_proven_mappings",
          all(m["verdict"] == "PROVEN_EQUIVALENT"
              for m in san["extension_mappings"])
          and non_proven > 0,
          f"SAN-FY2024: only PROVEN recorded as mappings; "
          f"{non_proven} non-proven elements never merged")

    # ---- TEF temporal fixture: en has 2 versions, es 1 ------------------
    env = next(v for v in tef["submission_variants"]
               if v["variant_id"].endswith("#en"))
    esv = next(v for v in tef["submission_variants"]
               if v["variant_id"].endswith("#es"))
    check("tef_temporal_shape",
          len(env["variant_versions"]) == 2
          and len(esv["variant_versions"]) == 1
          and env["variant_versions"][0]["observed"] is False
          and env["variant_versions"][1]["supersedes_variant_version_id"]
          == env["variant_versions"][0]["variant_version_id"]
          and ev13["affects"][0]["after_variant_version_id"]
          == env["variant_versions"][1]["variant_version_id"],
          "en: v1(unobserved)->v2(observed); es: single version")

    # ---- determinism: rebuild fixtures byte-identical -------------------
    before = {p.name: p.read_bytes()
              for p in (HERE / "fixtures").glob("*.json")}
    schema_before = (HERE / "canonical_model_v1.schema.json").read_bytes()
    subprocess.run([sys.executable, "-X", "utf8",
                    str(HERE / "g1e_build_fixtures.py")],
                   check=True, capture_output=True)
    check("fixtures_rebuild_deterministic",
          all((HERE / "fixtures" / n).read_bytes() == b
              for n, b in before.items())
          and (HERE / "canonical_model_v1.schema.json").read_bytes()
          == schema_before)

    n_pass = sum(1 for c in CHECKS if c["status"] == "PASS")
    verdict = "PASS" if n_pass == len(CHECKS) else "FAIL"
    print(f"\nG1-E: {verdict} ({n_pass}/{len(CHECKS)})")
    (HERE / "g1e_verify_results.json").write_bytes(json.dumps(
        {"verdict": verdict, "checks": CHECKS},
        indent=1, ensure_ascii=False).encode("utf-8"))
    return verdict == "PASS"


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
