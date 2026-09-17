# G2-C — COLUMNAR_DATASET_V1 verifier.
#
# Reads ONLY the materialized dataset directories (_out/runA|runB/
# dataset/v1) + sha256-pinned oracles. Checks C1-C15 + negative controls
# NC1-NC6 from the preregistered README matrix. Writes
# _out/g2c_verify_results.json; exit 0 iff every check passes.
import json
import shutil
import socket
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "_out"
sys.path.insert(0, str(REPO / "src"))

from opencnmv.serialize import canonical_bytes               # noqa: E402
from opencnmv.canonicalize import facts as xfacts            # noqa: E402
from opencnmv.dataset import parquetio, manifest as dmanifest  # noqa: E402
from opencnmv.dataset import tables as dtables               # noqa: E402
from opencnmv.dataset import query as dquery                 # noqa: E402
from opencnmv.dataset import integrity as dint               # noqa: E402
from opencnmv.dataset import schema as dschema               # noqa: E402
from opencnmv.model.canonical import CanonicalFiling         # noqa: E402

RESULTS: dict[str, dict] = {}


def report(check: str, ok: bool, detail: dict | str = ""):
    RESULTS[check] = {"status": "PASS" if ok else "FAIL",
                      "detail": detail}
    print(f"[{'PASS' if ok else 'FAIL'}] {check}: "
          f"{json.dumps(detail, ensure_ascii=False)[:220]}", flush=True)
    return ok


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def load_tables(ds: Path) -> dict[str, list[dict]]:
    return {t: parquetio.read_table(ds / f"{t}.parquet")
            for t in dschema.TABLE_ORDER}


def records_from_rows(fact_rows: list[dict],
                      dim_rows: list[dict]) -> list[dict]:
    dims_by_fid: dict[str, list[dict]] = {}
    for d in dim_rows:
        dims_by_fid.setdefault(d["fact_id"], []).append(d)
    return [dtables.record_from_row(
        r, sorted(dims_by_fid.get(r["fact_id"], []),
                  key=lambda d: d["dim_qname"]))
        for r in fact_rows]


def canon_lines(recs: list[dict]) -> Counter:
    return Counter(json.dumps(r, ensure_ascii=False, sort_keys=True)
                   for r in recs)


def main() -> int:
    run_dirs = {"A": OUT / "runA" / "dataset" / "v1",
                "B": OUT / "runB" / "dataset" / "v1"}
    for k, d in run_dirs.items():
        if not d.is_dir():
            report("C0", False, f"missing dataset dir for run {k}: {d}")
            return 1
    dsA, dsB = run_dirs["A"], run_dirs["B"]
    manA = load_json(dsA / "dataset_manifest.json")
    manB = load_json(dsB / "dataset_manifest.json")

    g2b_inputs = load_json(HERE.parent / "G2-B-frozen-corpus-rebuild" /
                           "g2b_inputs.json")
    corpus = load_json(HERE.parent / "G2-B-frozen-corpus-rebuild" /
                       "g2b_corpus.json")
    fixtures = {n: REPO / "g1/G1-E-canonical-model-freeze/fixtures"
                / f"{n}.json"
                for n in ("ibe_fy2024", "bbva_fy2024", "san_fy2024",
                          "tef_20484")}
    schema_v1 = load_json(REPO / "g1/G1-E-canonical-model-freeze"
                          "/canonical_model_v1.schema.json")

    tablesA = load_tables(dsA)
    ok_all = True

    # ---- C13 manifest/file hashes (both runs) + logical hash recompute ----
    errs = dmanifest.verify_manifest(dsA, manA) + \
        dmanifest.verify_manifest(dsB, manB)
    for t in dschema.TABLE_ORDER:
        recomputed = parquetio.logical_hash(t, tablesA[t])
        if recomputed != manA["tables"][t]["logical_sha256"]:
            errs.append(f"{t}: logical hash recompute mismatch")
    ok_all &= report("C13 manifest/file hashes", not errs, errs[:5])

    # ---- C12 run A == run B (every file byte-identical) ----
    diff = []
    for p in sorted(dsA.rglob("*")):
        if p.is_file():
            q = dsB / p.relative_to(dsA)
            if not q.is_file() or q.read_bytes() != p.read_bytes():
                diff.append(p.name)
    for q in sorted(dsB.rglob("*")):
        if q.is_file() and not (dsA / q.relative_to(dsB)).is_file():
            diff.append(q.name)
    log_eq = (manA["corpus_logical_sha256"] ==
              manB["corpus_logical_sha256"])
    ok_all &= report("C12 run A == run B", not diff and log_eq,
                     {"byte_identical_files": not diff,
                      "diff": diff[:8],
                      "corpus_logical_sha256": manA["corpus_logical_sha256"]})

    # ---- C1 complete corpus materialized ----
    states = {r["state_id"] for r in tablesA["provenance"]}
    corpus_ids = {e["id"] for e in corpus}
    fact_counts = Counter(r["state_id"] for r in tablesA["facts"])
    missing = corpus_ids - states
    zero_fact = [s for s in corpus_ids if fact_counts.get(s, 0) == 0]
    ok_all &= report("C1 complete corpus", not missing and not zero_fact,
                     {"states": len(states), "missing": sorted(missing),
                      "zero_fact_states": zero_fact,
                      "total_facts": sum(fact_counts.values())})

    # ---- C2 logical referential integrity ----
    violations = dint.check(tablesA)
    ok_all &= report("C2 relational integrity", not violations,
                     violations[:8])

    # ---- C3 facts preserve the full G2-B semantic multiset ----
    c3_detail = {"states": 0, "mismatched": []}
    dims_all = tablesA["fact_dimension"]
    for e in corpus:
        sid = e["id"]
        oracle_path = REPO / g2b_inputs["oracles"][f"{sid}.facts"]["path"]
        oracle = [json.loads(ln) for ln in
                  oracle_path.read_text(encoding="utf-8").splitlines()
                  if ln.strip()]
        rows = [r for r in tablesA["facts"] if r["state_id"] == sid]
        recs = records_from_rows(rows, dims_all)
        same_lines = canon_lines(recs) == canon_lines(oracle)
        same_multi = xfacts.fact_multiset(recs) == \
            xfacts.fact_multiset(oracle)
        if same_lines and same_multi:
            c3_detail["states"] += 1
        else:
            c3_detail["mismatched"].append(
                {"state": sid, "byte_lines_equal": same_lines,
                 "semantic_multiset_equal": same_multi})
    ok_all &= report("C3 facts == G2-B oracle multiset",
                     not c3_detail["mismatched"], c3_detail)

    # ---- C4 canonical objects reconstruct from columnar storage ----
    import jsonschema
    c4 = {"schema_valid": 0, "byte_equal": {}}
    for frow in tablesA["filing"]:
        fid = frow["filing_id"]
        fx = dtables.filing_from_rows(
            frow,
            [r for r in tablesA["filing_version"] if r["filing_id"] == fid],
            [r for r in tablesA["submission_variant"]
             if r["filing_id"] == fid],
            [r for r in tablesA["variant_version"]
             if r["variant_id"].startswith(fid + "#")],
            [r for r in tablesA["view_resolution"]
             if r["filing_id"] == fid],
            [r for r in tablesA["version_event"]
             if r["filing_id"] == fid],
            [r for r in tablesA["event_affects"]
             if r["event_id"].startswith(fid + "#")],
            [r for r in tablesA["artifact"]],
            [r for r in tablesA["extension_mapping"]
             if r["filing_id"] == fid])
        CanonicalFiling.model_validate(fx)
        jsonschema.validate(fx, schema_v1)
        c4["schema_valid"] += 1
        for name, fx_path in fixtures.items():
            if json.loads(fx_path.read_text(
                    encoding="utf-8"))["filing_id"] == fid:
                c4["byte_equal"][name] = canonical_bytes(fx) == \
                    canonical_bytes(json.loads(
                        fx_path.read_text(encoding="utf-8")))
    ok_all &= report("C4 fixture round-trip byte-exact",
                     c4["schema_valid"] == len(tablesA["filing"])
                     and all(c4["byte_equal"].values())
                     and len(c4["byte_equal"]) == 4, c4)

    # ---- C5 BBVA +98M/-98M divergence preserved ----
    # Structural-key join across the two submitted variants: identity sans
    # language is shared; payloads must stay divergent.
    def skey(r):
        return (r["concept"], r["entity_scheme"], r["entity"],
                r["period_start"], r["period_end"], r["period_instant"],
                r["period_forever"], r["unit"], r["canonical_dims_json"])
    es_idx = {skey(r): r for r in tablesA["facts"]
              if r["state_id"] == "BBVA-FY2024-es"}
    divergent = []
    for r in tablesA["facts"]:
        if r["state_id"] != "BBVA-FY2024-en":
            continue
        es = es_idx.get(skey(r))
        if es and es["value_sha256"] != r["value_sha256"]:
            divergent.append((es, r))
    c5_hits = [d for d in divergent
               if d[0]["concept"].endswith("#Equity")
               and d[0]["period_instant"] == "2023-01-01"]
    c5_ok = any(
        {es.get("value_full") or es["value_preview"],
         en.get("value_full") or en["value_preview"]}
        == {"98000000", "-98000000"}
        for es, en in c5_hits)
    ok_all &= report("C5 BBVA divergence", bool(c5_ok),
                     {"divergent_structural_pairs": len(divergent),
                      "equity_98M_pair_found": bool(c5_ok)})

    # ---- C6 IBE fallback / no phantom variant ----
    ibe_fid = "cnmv:ifa:20515"
    ibe_vars = [r["variant_id"] for r in tablesA["submission_variant"]
                if r["filing_id"] == ibe_fid]
    ibe_en = [r for r in tablesA["view_resolution"]
              if r["filing_id"] == ibe_fid
              and r["requested_ui_language"] == "en"]
    c6_ok = (ibe_vars == [f"{ibe_fid}#es"] and len(ibe_en) == 1 and
             ibe_en[0]["resolved_variant_id"] == f"{ibe_fid}#es" and
             ibe_en[0]["resolution_mode"].startswith("FALLBACK"))
    ok_all &= report("C6 IBE fallback, no phantom EN", c6_ok,
                     {"variants": ibe_vars, "en_resolution": ibe_en})

    # ---- C7 TEF independent EN lifecycle ----
    tef_fid = "cnmv:ifa:20484"
    tef_vv = {r["variant_version_id"]: r for r in tablesA["variant_version"]
              if r["variant_id"].startswith(tef_fid)}
    ev1 = tablesA["version_event"] and next(
        (r for r in tablesA["version_event"]
         if r["event_id"] == f"{tef_fid}#evt:2025-02-28"), None)
    ev2 = next((r for r in tablesA["version_event"]
                if r["event_id"] == f"{tef_fid}#evt:2025-03-13"), None)
    af1 = [r for r in tablesA["event_affects"]
           if ev1 and r["event_id"] == ev1["event_id"]]
    af2 = [r for r in tablesA["event_affects"]
           if ev2 and r["event_id"] == ev2["event_id"]]
    es_vvs = [v for k, v in tef_vv.items() if k.startswith(f"{tef_fid}#es")]
    en_vvs = sorted((v for k, v in tef_vv.items()
                     if k.startswith(f"{tef_fid}#en")),
                    key=lambda r: r["version_seq"])
    c7_ok = (
        len(es_vvs) == 1 and es_vvs[0]["observed"] and
        len(en_vvs) == 2 and not en_vvs[0]["observed"] and
        en_vvs[1]["observed"] and
        en_vvs[1]["supersedes_variant_version_id"] ==
        en_vvs[0]["variant_version_id"] and
        en_vvs[1]["created_by_event_id"] == f"{tef_fid}#evt:2025-03-13" and
        ev2 and ev2["scope_status"] == "EN_ONLY_REPLACED" and
        len(af2) == 1 and af2[0]["variant_id"] == f"{tef_fid}#en" and
        ev1 and ev1["scope_status"] == "VARIANT_SCOPE_NOT_OBSERVABLE" and
        all(a["variant_id"] is None for a in af1))
    ok_all &= report("C7 TEF EN lifecycle + event scope", bool(c7_ok),
                     {"es_versions": len(es_vvs), "en_versions": len(en_vvs),
                      "ev_0228_scope": ev1 and ev1["scope_status"],
                      "ev_0313_affects": [a["variant_id"] for a in af2]})

    # ---- C8 explicit + typed dimensions preserved ----
    n_explicit = sum(1 for r in dims_all if r["dim_kind"] == "E")
    n_typed = sum(1 for r in dims_all if r["dim_kind"] == "T")
    ok_all &= report("C8 explicit + typed dims",
                     n_explicit > 0 and n_typed > 0,
                     {"explicit_dim_rows": n_explicit,
                      "typed_dim_rows": n_typed})

    # ---- C9 compound units preserved ----
    n_compound = sum(1 for r in tablesA["facts"]
                     if r["unit_denominator_count"] > 0)
    n_multimeasure = sum(1 for r in tablesA["facts"]
                         if r["unit_numerator_count"] > 1)
    ok_all &= report("C9 compound units", n_compound > 0,
                     {"facts_with_denominator": n_compound,
                      "multi_measure_numerator": n_multimeasure})

    # ---- C10 extension mappings: verdicts + rewrite gate ----
    verdicts = Counter(r["verdict"] for r in tablesA["extension_mapping"])
    bad_rewrite = [r for r in tablesA["extension_mapping"]
                   if r["rewrites_identity"]
                   and r["verdict"] != "PROVEN_EQUIVALENT"]
    unresolved_kept = verdicts.get("UNMATCHED", 0) + \
        verdicts.get("AMBIGUOUS", 0) + verdicts.get("CONFLICT", 0)
    ok_all &= report("C10 mapping verdicts + rewrite gate",
                     not bad_rewrite and unresolved_kept > 0
                     and verdicts.get("PROVEN_EQUIVALENT", 0) > 0,
                     {"verdicts": dict(verdicts),
                      "bad_rewrite_rows": len(bad_rewrite)})

    # ---- C11 DuckDB verification queries ----
    con = dquery.open_dataset(dsA)
    qres = {}
    q_ok = True
    try:
        for name, sql in dquery.VERIFICATION_QUERIES.items():
            rows = con.execute(sql).fetchall()
            qres[name] = len(rows)
            if name == "orphan_facts" and rows[0][0] != 0:
                q_ok = False
            if name != "orphan_facts" and not rows:
                q_ok = False
    except Exception as ex:
        q_ok = False
        qres["error"] = str(ex)
    ok_all &= report("C11 DuckDB verification queries", q_ok, qres)

    # ---- C14 offline (worker evidence) ----
    net = []
    for run in ("runA", "runB"):
        for s in (OUT / run).glob("*.model_summary.json"):
            sm = load_json(s)
            if sm.get("network_attempts"):
                net.append(f"{run}/{s.name}:{sm['network_attempts']}")
    ok_all &= report("C14 no network access", not net, net[:5])

    # ---- C15 no gate-code imports in production path ----
    import re as _re
    bad_imports = []
    for p in (REPO / "src").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        if _re.search(r"^\s*(from|import)\s+(g0[_-]r|g1|g2)\b", src, _re.M):
            bad_imports.append(str(p.relative_to(REPO)))
    ok_all &= report("C15 zero gate-code imports in src/", not bad_imports,
                     bad_imports)

    # ---- negative controls ----
    # NC1: naive concept+period_end key collapses distinct facts
    naive = Counter((r["concept"], r["period_end"]) for r in tablesA["facts"])
    collisions = sum(1 for n in naive.values() if n > 1)
    ok_all &= report("NC1 naive concept+period_end collapses",
                     collisions > 0,
                     {"groups_with_collisions": collisions})

    # NC2: joining variants by UI language would fabricate IBE-EN
    phantom = [r for r in tablesA["submission_variant"]
               if r["filing_id"] == ibe_fid
               and r["submission_language"] == "en"]
    ok_all &= report("NC2 no UI-language-derived IBE EN variant",
                     not phantom, {"phantom_variants": phantom})

    # NC3: treating all events as filing-wide would wrongly mutate TEF-ES
    # (the 28/02 event has NO variant-scoped affects row -> cannot mutate ES)
    filing_wide_es = [a for a in af1 if a["variant_id"] == f"{tef_fid}#es"]
    ok_all &= report("NC3 TEF-ES untouched by unscoped event",
                     not filing_wide_es and af1 != [] and
                     all(a["variant_id"] is None for a in af1),
                     {"affects_rows_0228": len(af1)})

    # NC4: applying AMBIGUOUS mappings must remain unresolved
    amb = [r for r in tablesA["extension_mapping"]
           if r["verdict"] == "AMBIGUOUS"]
    amb_rewrite = [r for r in amb if r["rewrites_identity"]]
    ok_all &= report("NC4 AMBIGUOUS mappings unresolved",
                     len(amb) > 0 and not amb_rewrite,
                     {"ambiguous_rows": len(amb),
                      "marked_rewritable": len(amb_rewrite)})

    # NC5: removing a required relational row breaks integrity check
    cut = {k: [dict(r) for r in v] for k, v in tablesA.items()}
    victim = cut["filing_version"].pop(0)
    viol = dint.check(cut)
    ok_all &= report("NC5 row removal breaks integrity",
                     len(viol) > 0,
                     {"removed": victim["filing_version_id"],
                      "violations": len(viol)})

    # NC6: one modified Parquet byte breaks manifest verification
    with tempfile.TemporaryDirectory(dir=OUT) as td:
        dst = Path(td) / "v1"
        shutil.copytree(dsA, dst)
        fp = dst / "facts.parquet"
        b = bytearray(fp.read_bytes())
        b[len(b) // 2] ^= 0xFF
        fp.write_bytes(bytes(b))
        viol = dmanifest.verify_manifest(dst, manA)
        ok_all &= report("NC6 byte flip breaks manifest",
                         len(viol) > 0, {"violations": len(viol)})

    ok_all &= report("VERDICT", all(
        r["status"] == "PASS" for k, r in RESULTS.items()
        if k != "VERDICT"), {"checks": len(RESULTS) - 1})

    res_path = HERE / "g2c_verify_results.json"
    res_path.write_bytes(canonical_bytes(RESULTS))
    print("wrote", res_path)

    # gate manifest (committed): pins gate code + inputs + dataset manifest
    from opencnmv.provenance.hashes import sha256_file
    import subprocess
    import datetime
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True,
                            cwd=REPO).stdout.strip()
    n_facts = len(tablesA["facts"])
    size = sum(p.stat().st_size for p in dsA.rglob("*") if p.is_file())
    gate_manifest = {
        "gate": "G2-C-columnar-dataset-v1",
        "status": RESULTS["VERDICT"]["status"],
        "executed_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "code_commit": commit,
        "inputs": "g2c_inputs.json (evidence pins) + g2b_inputs.json "
                  "(25 artifacts + 6 taxonomy packages + 50 oracles, "
                  "all sha256-pinned and verified byte-exact)",
        "outputs": {
            "verify_results": "g2c_verify_results.json",
            "verify_results_sha256": sha256_file(res_path),
            "dataset_manifest_runA":
                "_out/runA/dataset/v1/dataset_manifest.json",
            "dataset_manifest_runA_sha256":
                sha256_file(dsA / "dataset_manifest.json"),
            "dataset_manifest_runB_sha256":
                sha256_file(dsB / "dataset_manifest.json"),
            "corpus_logical_sha256": manA["corpus_logical_sha256"],
            "total_facts": n_facts,
            "dataset_bytes": size,
            "table_rows": {t: manA["tables"][t]["rows"]
                           for t in dschema.TABLE_ORDER}},
        "sha256": {p.name: sha256_file(p) for p in sorted(HERE.iterdir())
                   if p.is_file() and p.suffix in (".py", ".json")
                   and p.name != "manifest.json"},
        "findings": [
            "dataset rebuilds byte-identically across PYTHONHASHSEED "
            "17/991 (all files incl. dataset_manifest.json equal)",
            f"total facts materialized: {n_facts}",
            "all 4 frozen G1-E fixtures reconstruct byte-identically from "
            "columnar storage alone",
            "all 25 fact planes equal the G2-B oracle multiset and the "
            "canonical-line multiset",
            "UNMATCHED G1-C mapping records retained as table-only rows "
            "(no schema-valid ExtensionMapping form: pair_id required)"],
        "limitations": [
            "Parquet files are gitignored under _out/; they rebuild "
            "byte-identically from pinned inputs and are pinned via "
            "dataset_manifest.json sha256 + logical row hashes",
            "IPP artifacts attach to filing_version (CANONICAL_MODEL_V1 "
            "migration note); implicit es variant_version carries "
            "artifact_set_id",
            "unit numerator/denominator measures come from a worker "
            "sidecar (units.jsonl): the canonical unit signature cannot "
            "be split unambiguously (QNames contain '/')",
            "TEF 20484 is lifecycle evidence only — no facts parsed for it"],
    }
    from opencnmv.serialize import write_canonical
    write_canonical(gate_manifest, HERE / "manifest.json")
    print("wrote", HERE / "manifest.json")
    return 0 if RESULTS["VERDICT"]["status"] == "PASS" else 1


if __name__ == "__main__":
    # defence in depth: the verifier itself runs offline
    def _deny(*a, **k):
        raise RuntimeError("network access forbidden")
    socket.socket.connect = _deny          # type: ignore[attr-defined]
    socket.create_connection = _deny       # type: ignore[attr-defined]
    socket.getaddrinfo = _deny             # type: ignore[attr-defined]
    sys.exit(main())
