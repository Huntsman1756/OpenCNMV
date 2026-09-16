# G2-B verifier — PASS/FAIL only, reads rebuild outputs.
#   B1 input sha verification            all frozen inputs PASS
#   B2 production parse                  25/25 OK, ioerr=0, DTS complete
#   B3 semantic equality vs frozen       facts.jsonl byte-equal + multiset
#   B4 typed dimensions                  real IPP typed dims reproduced
#   B5 Control A                         API multiset == Arelle OIM multiset
#   B6 offline purity                    0 network attempts, 0 gate imports,
#                                        DTS resolved only from bounded dirs
#   B7 determinism                       runA == runB (bytes + corpus hash)
#   B8 negative dependency controls      FAILS_AS_EXPECTED x2
import json, re, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "_out"
sys.path.insert(0, str(REPO / "src"))
from opencnmv.provenance.hashes import sha256_file          # noqa: E402
from opencnmv.canonicalize import facts as xfacts           # noqa: E402


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main():
    corpus = load_json(HERE / "g2b_corpus.json")
    inputs = load_json(HERE / "g2b_inputs.json")
    results = load_json(OUT / "rebuild_results.json")
    checks = []

    # --- B1
    bad = [k for g in ("artifacts", "taxonomy_packages", "oracles")
           for k, rec in inputs[g].items()
           if sha256_file(REPO / rec["path"]).upper() != rec["sha256"]]
    checks.append(("B1_input_sha_all_pinned", not bad,
                   {"mismatches": bad}))

    # --- B2
    runA = results["runs"]["A"]
    not_ok = {k: v for k, v in runA.items() if v.get("status") != "OK"}
    ioerr = {k: v for k, v in runA.items()
             if (load_json(OUT / "runA" / f"{k}.model_summary.json")
                 ["offline_evidence"]["io_errors"]) > 0}
    dts_ok = True
    for e in corpus:
        s = load_json(OUT / "runA" / f"{e['id']}.model_summary.json")
        for d in s["dts_resolution"]:
            if d["resolved_from"] not in ("taxonomy_package", "local_input",
                                          "arelle_cache"):
                dts_ok = False
    checks.append(("B2_parse_25_ok_ioerr0_dts",
                   not not_ok and not ioerr and dts_ok,
                   {"not_ok": list(not_ok), "ioerr": list(ioerr)}))

    # --- B3 content + multiset equality vs frozen oracle + summary counts
    # The frozen oracles were written in text mode (CRLF on Windows); the
    # durable serializer is LF-canonical, so byte equality is asserted after
    # CRLF->LF normalisation of the oracle, AND field-level multiset equality
    # (concept/entity/period/dims/unit/decimals/nil/lang/value_sha256).
    b3 = {"byte_equal": [], "lf_normalized_equal": [], "diff": [],
          "multiset_diff": [], "count_diff": []}
    for e in corpus:
        fid = e["id"]
        prod = (OUT / "runA" / f"{fid}.facts.jsonl").read_bytes()
        orac = (REPO / e["oracle_facts"]).read_bytes()
        if prod == orac:
            b3["byte_equal"].append(fid)
        elif prod == orac.replace(b"\r\n", b"\n"):
            b3["lf_normalized_equal"].append(fid)
        else:
            b3["diff"].append(fid)
            precs = [json.loads(l) for l in
                     prod.decode("utf-8").splitlines() if l.strip()]
            orecs = [json.loads(l) for l in
                     orac.decode("utf-8").splitlines() if l.strip()]
            if xfacts.fact_multiset(precs) != xfacts.fact_multiset(orecs):
                b3["multiset_diff"].append(fid)
        s = load_json(OUT / "runA" / f"{fid}.model_summary.json")
        o = load_json(REPO / e["oracle_summary"])
        oc = o.get("counts", {})
        sc = s.get("counts", {})
        diff = {k: (sc.get(k), oc.get(k))
                for k in ("facts", "contexts", "units", "concepts",
                          "dts_documents", "nil_facts")
                if sc.get(k) != oc.get(k)}
        if diff:
            b3["count_diff"].append({fid: diff})
    checks.append(("B3_facts_equal_to_frozen_oracle",
                   not b3["diff"] and not b3["multiset_diff"]
                   and not b3["count_diff"],
                   b3))

    # --- B4 typed dimensions reproduced (real IPP corpus) + full-unit selftest
    td = {}
    for e in corpus:
        if e["kind"] != "ipp":
            continue
        s = load_json(OUT / "runA" / f"{e['id']}.model_summary.json")
        o = load_json(REPO / e["oracle_summary"])
        td[e["id"]] = (s["counts"]["contexts_typed_dims"],
                       o["counts"].get("contexts_typed_dims"))
    td_bad = {k: v for k, v in td.items() if v[0] != v[1]}
    # unit completeness: corpus may carry no compound units — assert the
    # canonical signature preserves num+den on a synthetic stub.
    class _Q:
        def __init__(s, n, l): s.namespaceURI, s.localName = n, l
    class _U:
        measures = ([_Q("ns:x", "b"), _Q("ns:x", "a")], [_Q("ns:y", "c")])
    unit_selftest = xfacts.unit_sig(_U()) == "ns:x#a*ns:x#b/ns:y#c"
    corpus_compound = any("/" in (json.loads(l).get("unit") or "")
                          for e in corpus for l in
                          (OUT / "runA" / f"{e['id']}.facts.jsonl")
                          .read_text(encoding="utf-8").splitlines())
    checks.append(("B4_typed_dims_and_full_unit",
                   not td_bad and unit_selftest,
                   {"typed_dim_diff": td_bad,
                    "compound_unit_selftest": unit_selftest,
                    "corpus_compound_units": corpus_compound}))

    # --- B5 Control A
    b5bad = [e["id"] for e in corpus
             if not load_json(OUT / "runA" / f"{e['id']}.model_summary.json")
             .get("control_A", {}).get("fact_multiset_equal")]
    checks.append(("B5_controlA_api_eq_oim_25", not b5bad, {"bad": b5bad}))

    # --- B6 offline purity
    net = {k: v for k, v in runA.items() if v.get("net", 0) != 0}
    gate_import = []
    for p in (REPO / "src").rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        if re.search(r"\b(import|from)\s+(g0[-_]r|g1|r1[0-9]|r0[0-9])\b", t) \
                or re.search(r"[\"'](?:g0-r|g1)/", t):
            gate_import.append(str(p.relative_to(REPO)))
    checks.append(("B6_offline_no_gate_code",
                   not net and not gate_import,
                   {"net_attempts": net, "gate_import_refs": gate_import}))

    # --- B7 determinism runA vs runB
    b7diff, corpus_hash = [], {}
    for rn in ("A", "B"):
        shas = {e["id"]: sha256_file(OUT / f"run{rn}" / f"{e['id']}.facts.jsonl")
                for e in corpus}
        import hashlib
        corpus_hash[rn] = hashlib.sha256(
            "".join(shas[k] for k in sorted(shas)).encode()).hexdigest()
        if rn == "B":
            shaA = {e["id"]: sha256_file(OUT / "runA" / f"{e['id']}.facts.jsonl")
                    for e in corpus}
            b7diff = [k for k in shas if shas[k] != shaA[k]]
    checks.append(("B7_runA_eq_runB",
                   not b7diff and corpus_hash["A"] == corpus_hash["B"],
                   {"diff": b7diff, "corpus_hash": corpus_hash}))

    # --- B8 negative controls must NOT parse cleanly
    nc = results["negative_controls"]
    b8 = {}
    for k, v in nc.items():
        summ = list((OUT / "_negative_controls").rglob(f"{v['filing']}.model_summary.json"))
        ok = v.get("status") == "OK"
        if summ:
            ok = ok and load_json(summ[0])["offline_evidence"]["io_errors"] == 0
        b8[k] = "FAILED_AS_EXPECTED" if not ok else "UNEXPECTEDLY_PARSED"
    checks.append(("B8_negative_controls_fail",
                   all(v == "FAILED_AS_EXPECTED" for v in b8.values()), b8))

    npass = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        if not ok:
            print("     ", json.dumps(detail)[:800])
    print(f"\nG2-B: {'PASS' if npass == len(checks) else 'FAIL'} "
          f"({npass}/{len(checks)})")
    (OUT / "verify_results.json").write_bytes(json.dumps(
        {"verdict": "PASS" if npass == len(checks) else "FAIL",
         "checks": [{"name": n, "status": "PASS" if ok else "FAIL",
                     "detail": d} for n, ok, d in checks]},
        indent=1, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
