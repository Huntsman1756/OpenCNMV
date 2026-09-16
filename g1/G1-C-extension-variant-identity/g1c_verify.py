# G1-C — verifier: determinism + gate checks for EXTENSION_VARIANT_IDENTITY.
#
#   structure determinism : evidence/structure/*.structure.json (run1) vs
#                           _runs/structure-run2/* sha equality
#   mapping determinism   : g1c_map recomputation -> identical mapping files
#   dataset determinism   : g1c_compare_mapped recomputation -> identical sha
#   adversarial           : synthetic shared-anchor case must be AMBIGUOUS
#   natural ambiguity     : corpus must contain >=1 real AMBIGUOUS verdict
#   preservation          : BBVA +98M/-98M still DIVERGENT in mapped dataset
#   no new divergences    : every mapped DIVERGENT also exists in baseline
#   proven-only rewrite   : only PROVEN_EQUIVALENT pairs carry pair_id
import json, subprocess, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EV = HERE / "evidence"
STR = EV / "structure"
MAP = EV / "mapping"
OUT = EV / "compare_mapped"
RUNS = HERE / "_runs"
G1B = REPO / "g1/G1-B-dual-language-capture/evidence/compare"

sys.path.insert(0, str(HERE))
import g1c_map  # noqa: E402


def sha(p: Path):
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    checks = {}

    # 1. structure determinism (run2 must have been produced by
    #    `g1c_structure.py 2 all` into _runs/structure-run2)
    r1 = {x.stem.replace(".structure", ""): sha(x)
          for x in STR.glob("*.structure.json")}
    r2dir = RUNS / "structure-run2"
    r2 = {x.stem.replace(".structure", ""): sha(x)
          for x in r2dir.glob("*.structure.json")} if r2dir.exists() else {}
    checks["structure_extraction_deterministic"] = {
        "pass": bool(r1) and r1 == r2,
        "run1": len(r1), "run2": len(r2),
        "mismatched": [k for k in r1 if r2.get(k) != r1[k]]}

    # 2. mapping determinism: recompute each filing, compare file bytes
    mism = []
    for issuer, fy in g1c_map.DUAL:
        fid = f"{issuer}-{fy}"
        doc = g1c_map.map_filing(issuer, fy)
        recs = doc.pop("records")
        recomputed = json.dumps({"filing": fid, "records": recs},
                                indent=1, ensure_ascii=False,
                                sort_keys=True).encode("utf-8")
        if (MAP / f"{fid}.mapping.json").read_bytes() != recomputed:
            mism.append(fid)
    checks["mapping_dataset_deterministic"] = {"pass": not mism,
                                               "mismatched": mism}

    # 3. mapped dataset determinism: re-run compare, compare sha
    import importlib
    import g1c_compare_mapped as CM
    before = sha(OUT / "g1c_mapped_dataset.json")
    importlib.reload(CM)
    CM.main()
    after = sha(OUT / "g1c_mapped_dataset.json")
    checks["mapped_dataset_deterministic"] = {"pass": before == after,
                                              "sha256": after}

    # 4. adversarial + natural ambiguity
    mres = json.loads((MAP / "mapping_results.json").read_text(encoding="utf-8"))
    checks["adversarial_ambiguity_control"] = \
        mres["checks"]["adversarial_ambiguity_control"]
    amb = sum(v.get("AMBIGUOUS", 0)
              for r in mres["results"] for v in [r["verdict_counts"]])
    checks["natural_ambiguity_present"] = {
        "pass": amb >= 1,
        "ambiguous_verdicts_in_corpus": amb,
        "note": "shared-anchor same-structure elements must not be paired"}

    # 5. preservation of the known divergence + no new divergences
    base = json.loads((G1B / "g1b_divergence_dataset.json")
                      .read_text(encoding="utf-8"))
    mapped = json.loads((OUT / "g1c_mapped_dataset.json")
                        .read_text(encoding="utf-8"))
    base_div = [r for r in base["records"]
                if r["class"] == "DIVERGENT_SUBMISSION_FACT"]
    map_div = [r for r in mapped["records"]
               if r["class"] == "DIVERGENT_SUBMISSION_FACT"]
    bbva = next((r for r in map_div
                 if r["filing"] == "BBVA-FY2024"
                 and r["key"]["concept"].endswith("#Equity")
                 and r["key"]["period"] == "2023-01-01"), None)
    checks["bbva_equity_98m_divergent_preserved"] = {
        "pass": bbva is not None
                and bbva["es"]["value"] == "98000000"
                and bbva["en"]["value"] == "-98000000",
        "observed": {"es": bbva["es"]["value"],
                     "en": bbva["en"]["value"]} if bbva else None}
    checks["no_new_divergences_vs_baseline"] = {
        "pass": len(map_div) == len(base_div)
                and all(m["filing"] == b["filing"]
                        and m["key"]["concept"].endswith(
                            "#" + b["key"]["concept"].rsplit("#", 1)[-1])
                        for m, b in zip(map_div, base_div)),
        "baseline_divergent": len(base_div),
        "mapped_divergent": len(map_div)}

    # 6. proven-only rewrite: every pair_id record is PROVEN
    all_recs = []
    for issuer, fy in g1c_map.DUAL:
        all_recs += json.loads(
            (MAP / f"{issuer}-{fy}.mapping.json")
            .read_text(encoding="utf-8"))["records"]
    checks["only_proven_pairs_have_pair_id"] = {
        "pass": all(("pair_id" in r) == (r["verdict"] == "PROVEN_EQUIVALENT")
                    for r in all_recs),
        "proven": sum(1 for r in all_recs
                      if r["verdict"] == "PROVEN_EQUIVALENT")}

    totals = {"mapping_verdicts": dict(Counter(r["verdict"]
                                             for r in all_recs))}
    verdict = "PASS" if all(c["pass"] for c in checks.values()) else "FAIL"
    out = {"gate": "G1-C EXTENSION_VARIANT_IDENTITY", "verdict": verdict,
           "checks": checks, **totals}
    (EV / "g1c_results.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    print("G1-C verdict:", verdict)
    for k, v in checks.items():
        print(f"  {'PASS' if v['pass'] else 'FAIL'}  {k}")
    print("mapping verdict totals:", totals["mapping_verdicts"])
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
