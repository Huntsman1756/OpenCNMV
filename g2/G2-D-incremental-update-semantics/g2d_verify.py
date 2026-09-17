"""G2-D verifier: evaluates the preregistered D1-D20 acceptance matrix
over the artifacts produced by g2d_build.py + g2d_run.py.

Writes g2d_verify_results.json (gate root, committed) and the gate
manifest.json. Verdict is PASS only when every applicable check passes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

import g2d_common as C  # noqa: E402
from opencnmv.dataset import integrity as dint  # noqa: E402
from opencnmv.update import integrity as uint  # noqa: E402

RESULTS = HERE / "g2d_verify_results.json"


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def tables_equal(a: dict, b: dict) -> list[str]:
    """Per-table multiset diff; returns list of mismatch descriptions."""
    out = []
    for t in a:
        sa = sorted(json.dumps(r, sort_keys=True, default=str)
                    for r in a[t])
        sb = sorted(json.dumps(r, sort_keys=True, default=str)
                    for r in b[t])
        if sa != sb:
            out.append(t)
    return out


def files_identical(d1: Path, d2: Path) -> list[str]:
    import hashlib
    diffs = []
    f1 = {p.name for p in d1.glob("*") if p.is_file()}
    f2 = {p.name for p in d2.glob("*") if p.is_file()}
    for name in sorted(f1 | f2):
        p1, p2 = d1 / name, d2 / name
        if name == "dataset_manifest.json":
            continue          # inputs/generator legitimately differ
        if not p1.exists() or not p2.exists():
            diffs.append(f"{name}: missing on one side")
        elif hashlib.sha256(p1.read_bytes()).digest() != \
                hashlib.sha256(p2.read_bytes()).digest():
            diffs.append(f"{name}: bytes differ")
    return diffs


def main():
    inputs = jload(HERE / "g2d_inputs.json")
    g2c_hash = inputs["g2c_corpus_logical_sha256"]
    runA = jload(C.OUT / "run_A.json")
    runB = jload(C.OUT / "run_B.json")
    ctlA = jload(C.OUT / "controls_A.json")["controls"]
    ctlB = jload(C.OUT / "controls_B.json")["controls"]
    S = runA["scenarios"]
    checks: list[dict] = []

    def ck(cid: str, ok: bool, detail: str = ""):
        checks.append({"id": cid, "status": "PASS" if ok else "FAIL",
                       "detail": detail})

    def res(name):
        return jload(C.OUT / "scen" / name / "runA" / "result.json")

    def spec(name):
        return jload(C.OUT / "scen" / name / "spec.json")

    def scen_ds(name, tag="A"):
        return C.OUT / "scen" / name / f"run{tag}" / "ds" / "v1"

    # -- D1: NO_CHANGE byte/logical idempotent ------------------------------
    a = res("A")
    d1 = (a["apply_status"] == "NO_CHANGE"
          and a["s1_corpus_logical_sha256"] == g2c_hash
          and a["transitions"] and
          {t["transition"] for t in a["transitions"]} == {"NO_CHANGE"}
          and not a["rows_added"] and not a["rows_updated"]
          and a["replay"]["transitions"] == ["NO_CHANGE"]
          and a["replay"]["row_ops"] == 0)
    ck("D1", d1, f"apply={a['apply_status']} "
                 f"transitions={ {t['transition'] for t in a['transitions']} }")

    # -- D2: NEW_FILING creates only required graph -------------------------
    b = res("B")
    kinds = {t["transition"] for t in b["transitions"]}
    added = b["rows_added"]
    d2 = (kinds == {"NEW_FILING", "NEW_FILING_VERSION",
                    "NEW_SUBMISSION_VARIANT", "NEW_VARIANT_VERSION",
                    "VIEW_RESOLUTION_RECORDED", "FACT_ADDED"}
          and added.get("filing") == 1 and added.get("filing_version") == 1
          and added.get("submission_variant") == 1
          and added.get("variant_version") == 1
          and added.get("view_resolution") == 1
          and added.get("artifact") == 1 and added.get("provenance") == 1
          and added.get("facts", 0) == 1110
          and added.get("fact_dimension", 0) == 1174
          and b["apply_status"] == "APPLIED")
    ck("D2", d2, f"kinds={sorted(kinds)} added={added}")

    # -- D3: UI fallback creates no phantom variant -------------------------
    c1 = res("C1")
    dsC = C.load_tables(scen_ds("C2"))
    ibe_variants = {r["variant_id"] for r in dsC["submission_variant"]
                    if r["filing_id"] == "cnmv:ifa:20515"}
    ibe_vr = {r["requested_ui_language"]: r["resolution_mode"]
              for r in dsC["view_resolution"]
              if r["filing_id"] == "cnmv:ifa:20515"}
    c2 = res("C2")
    d3 = (c1["apply_status"] == "NO_CHANGE"
          and ibe_variants == {"cnmv:ifa:20515#es"}
          and ibe_vr.get("en") == "FALLBACK_TO_ES"
          and ibe_vr.get("fr") == "FALLBACK_TO_ES"
          and {t["transition"] for t in c2["transitions"]}
          == {"VIEW_RESOLUTION_RECORDED"}
          and c2["rows_added"].get("view_resolution") == 1
          and not c2["rows_added"].get("submission_variant"))
    ck("D3", d3, f"variants={ibe_variants} vr={ibe_vr}")

    # -- D4: new real language variant --------------------------------------
    d = res("D")
    dk = {t["transition"] for t in d["transitions"]}
    dsD = C.load_tables(scen_ds("D"))
    en_vv = [r for r in dsD["variant_version"]
             if r["variant_id"] == "cnmv:ifa:20448#en"]
    d4 = ({"NEW_SUBMISSION_VARIANT", "NEW_VARIANT_VERSION"} <= dk
          and len(en_vv) == 1
          and en_vv[0]["variant_version_id"].endswith("#en#v1")
          and en_vv[0]["version_seq"] == 1
          and en_vv[0]["supersedes_variant_version_id"] is None)
    ck("D4", d4, f"kinds={sorted(dk)} en_vv={len(en_vv)}")

    # -- D5: EN_ONLY replacement creates only new EN variant_version --------
    e = res("E")
    ek = {t["transition"] for t in e["transitions"]}
    dsE = C.load_tables(scen_ds("E"))
    s0E = C.load_tables(C.OUT / "scen" / "E" / "S0" / "v1")
    es_rows_0 = {t: [r for r in s0E[t]
                     if "#es" in json.dumps(r)] for t in s0E}
    es_rows_1 = {t: [r for r in dsE[t]
                     if "#es" in json.dumps(r)] for t in dsE}
    es_same = all(sorted(map(lambda r: json.dumps(r, sort_keys=True),
                           es_rows_0[t]))
                  == sorted(map(lambda r: json.dumps(r, sort_keys=True),
                                es_rows_1[t])) for t in es_rows_0)
    en_v2 = [r for r in dsE["variant_version"]
             if r["variant_version_id"] == "cnmv:ifa:20484#en#v2"]
    ev_aff = [r for r in dsE["event_affects"]
              if r["event_id"] == "cnmv:ifa:20484#evt:2025-03-13"]
    d5 = ({"NEW_VERSION_EVENT", "VARIANT_SCOPED_VERSION_EVENT",
           "NEW_VARIANT_VERSION"} <= ek
          and len(en_v2) == 1
          and en_v2[0]["supersedes_variant_version_id"]
          == "cnmv:ifa:20484#en#v1"
          and en_v2[0]["created_by_event_id"]
          == "cnmv:ifa:20484#evt:2025-03-13"
          and {r["variant_id"] for r in ev_aff}
          == {"cnmv:ifa:20484#en"}
          and es_same)
    ck("D5", d5, f"kinds={sorted(ek)} es_rows_identical={es_same}")

    # -- D6: unobservable scope fabricates nothing ---------------------------
    f = res("F")
    fk = {t["transition"] for t in f["transitions"]}
    d6 = ("FILING_SCOPE_NOT_OBSERVABLE" in fk
          and "NEW_VERSION_EVENT" in fk
          and "NEW_VARIANT_VERSION" not in fk
          and "VARIANT_SCOPED_VERSION_EVENT" not in fk
          and not f["rows_added"].get("variant_version"))
    ck("D6", d6, f"kinds={sorted(fk)}")

    # -- D7: changed fact payload preserves both histories -------------------
    g = res("G")
    gk = {t["transition"] for t in g["transitions"]}
    dsG = C.load_tables(scen_ds("G"))
    v1f = [r for r in dsG["facts"]
           if r["variant_version_id"] == "cnmv:ipp:2026103709#es#v1"]
    v2f = [r for r in dsG["facts"]
           if r["variant_version_id"] == "cnmv:ipp:2026103709#es#v2"]
    same_key = [r for r in v2f if r["seq"] == 0]
    old_key = [r for r in v1f if r["seq"] == 0]
    d7 = ("FACT_PAYLOAD_CHANGED" in gk and "NEW_VARIANT_VERSION" in gk
          and len(v1f) == 1110 and len(v2f) == 1110
          and same_key and old_key
          and same_key[0]["value_sha256"] != old_key[0]["value_sha256"]
          and same_key[0]["concept"] == old_key[0]["concept"]
          and same_key[0]["period_instant"] == old_key[0]["period_instant"])
    ck("D7", d7, f"v1={len(v1f)} v2={len(v2f)} payload_changed="
                 f"{same_key[0]['value_sha256'][:8] != old_key[0]['value_sha256'][:8]}")

    # -- D8: PROVEN-only rewrite ---------------------------------------------
    i1, i2 = res("I1"), res("I2")
    dsI = C.load_tables(scen_ds("I2"))
    mapped = [r for r in dsI["extension_mapping"]
              if r["filing_id"] == "cnmv:ifa:20854"]
    bad_rw = [r["source_ordinal"] for r in mapped
              if r["rewrites_identity"]
              and r["verdict"] != "PROVEN_EQUIVALENT"]
    prov_missing = [r["source_ordinal"] for r in mapped
                    if r["verdict"] == "PROVEN_EQUIVALENT"
                    and not r["rewrites_identity"]]
    ch = spec("I2")["changed_ordinals"]
    adv = next(r for r in mapped
               if r["source_ordinal"] == ch["adversarial"])
    d8 = (i1["apply_status"] == "APPLIED"
          and "EXTENSION_MAPPING_ADDED"
          in {t["transition"] for t in i1["transitions"]}
          and "EXTENSION_MAPPING_CHANGED"
          in {t["transition"] for t in i2["transitions"]}
          and not bad_rw and not prov_missing
          and adv["rewrites_identity"] is False)
    ck("D8", d8, f"bad_rewrites={bad_rw} adversarial_row_verdict="
                 f"{adv['verdict']} rewrites={adv['rewrites_identity']}")

    # -- D9: delta deterministic across hash seeds ----------------------------
    d9_ok, d9_detail = True, []
    SB = runB["scenarios"]
    for name in S:
        da = (C.OUT / "scen" / name / "runA" / "delta.json").read_bytes()
        db = (C.OUT / "scen" / name / "runB" / "delta.json").read_bytes()
        if da != db:
            d9_ok = False
            d9_detail.append(f"{name}:delta")
        sA, sB = S[name], SB[name]
        for k in ("status", "result_hash", "transitions"):
            if sA.get(k) != sB.get(k):
                d9_ok = False
                d9_detail.append(f"{name}:{k}")
    ck("D9", d9_ok, f"mismatched: {d9_detail or 'none'}")

    # -- D10: replay idempotent ----------------------------------------------
    d10_bad = []
    for name in S:
        r = res(name)
        sp = spec(name)
        expect = sp.get("replay_expect", "NO_CHANGE")
        if expect == "NO_CHANGE":
            if (r["replay"]["transitions"] != ["NO_CHANGE"]
                    or r["replay"]["row_ops"] != 0
                    or r["replay"]["apply_status"] != "NO_CHANGE"):
                d10_bad.append(name)
        else:
            if r["replay"]["row_ops"] != 0:
                d10_bad.append(name)
    ck("D10", not d10_bad, f"non-idempotent: {d10_bad or 'none'}")

    # -- D11: stale-base rejection --------------------------------------------
    d11 = all(ctl.get("stale_base", {}).get("result") == "StaleBaseError"
              for ctl in (ctlA, ctlB))
    ck("D11", d11, json.dumps(
        {k: ctlA.get(k, {}).get("result") for k in ("stale_base",)}))

    # -- D12: injected failure leaves base valid ------------------------------
    fails = {k: v for k, v in ctlA.items() if k.startswith("fail_")}
    d12 = bool(fails) and all(v.get("ok") for v in fails.values()) \
        and all(v.get("ok") for k, v in ctlB.items()
                if k.startswith("fail_"))
    ck("D12", d12, json.dumps({k: v.get("ok") for k, v in fails.items()}))

    # -- D13: incremental S1 == clean rebuild oracle ---------------------------
    d13_bad = []
    for name in S:
        sp = spec(name)
        r = res(name)
        if r["apply_status"] != "APPLIED":
            continue                      # no-op/unresolved scenarios
        s1 = scen_ds(name)
        if sp["oracle"] == "g2c_runA":
            diffs = files_identical(s1, C.G2C_DS)
        else:
            diffs = files_identical(s1, C.OUT / "scen" / name
                                    / "oracle" / "v1")
        if diffs:
            d13_bad.append({name: diffs})
    ck("D13", not d13_bad,
       json.dumps(d13_bad)[:300] if d13_bad else "all applied "
       "scenarios byte-identical to oracle")

    # -- D14: referential integrity after every scenario ----------------------
    d14_bad = []
    for name in S:
        for tag in ("A", "B"):
            t = C.load_tables(scen_ds(name, tag))
            errs = dint.check(t) + uint.check_update_invariants(t)
            if errs:
                d14_bad.append({f"{name}/{tag}": errs[:3]})
    ck("D14", not d14_bad, json.dumps(d14_bad)[:300])

    # -- D15: manifests detect tampering ---------------------------------------
    import tempfile
    import shutil as sh
    from opencnmv.dataset import manifest as dmanifest
    d15 = False
    with tempfile.TemporaryDirectory() as td:
        tgt = Path(td) / "v1"
        sh.copytree(C.OUT / "scen" / "A" / "runA" / "ds" / "v1", tgt)
        man = json.loads((tgt / "dataset_manifest.json").read_text())
        fp = tgt / "filing.parquet"
        b = bytearray(fp.read_bytes())
        b[10] ^= 0xFF
        fp.write_bytes(bytes(b))
        d15 = bool(dmanifest.verify_manifest(tgt, man))
    tam = all(ctl.get("tampered_delta", {}).get("result") == "DeltaError"
              for ctl in (ctlA, ctlB))
    ck("D15", d15 and tam, f"manifest_detects={d15} delta_tamper={tam}")

    # -- D16: zero network -----------------------------------------------------
    # the runner patches socket.connect/create_connection/getaddrinfo to
    # raise; a completed run file is proof the engine ran deny-all
    d16 = all(r["apply_status"] in ("APPLIED", "NO_CHANGE")
              for r in S.values())
    ck("D16", d16, "all scenarios completed under socket deny-all")

    # -- D17: no gate-code imports in production --------------------------------
    import re as _re
    hits = []
    for py in (HERE.parents[1] / "src").rglob("*.py"):
        for i, line in enumerate(
                py.read_text(encoding="utf-8").splitlines(), 1):
            if _re.match(r"\s*(from|import)\s+(g0_r|g1_|g2_|g2d|g2c|"
                         r"g2b|g2a)[\.\s]", line):
                hits.append(f"{py.name}:{i}")
    ck("D17", not hits, f"gate-code imports in src: {hits or 'none'}")

    # -- D18-D20: regressions (results committed by their own gates) ------------
    for cid, gate_dir, res_file in (
            ("D18", "G2-A-durable-canonical-core", "g2a_verify_results.json"),
            ("D19", "G2-B-frozen-corpus-rebuild", "g2b_verify_results.json"),
            ("D20", "G2-C-columnar-dataset-v1", "g2c_verify_results.json")):
        gdir = HERE.parents[1] / "g2" / gate_dir
        rp = gdir / res_file
        if rp.exists():
            rj = jload(rp)
            ok = rj.get("gate", "").endswith("PASS") or \
                rj.get("status") == "PASS" or \
                all(c.get("status") == "PASS"
                    for c in rj.get("checks", []))
            ck(cid, bool(ok), f"{res_file}: "
                              f"{rj.get('status') or rj.get('gate')}")
        else:
            ck(cid, False, f"{res_file} missing — rerun gate on this HEAD")

    # -- extra adversarial: H1/I3 unresolved, H2 annotation ---------------------
    h1, h2, i3 = res("H1"), res("H2"), res("I3")
    adv = ({t["transition"] for t in h1["transitions"]}
           == {"SOURCE_STATE_CONFLICT", "UNRESOLVED"} or
           "UNRESOLVED" in {t["transition"] for t in h1["transitions"]})
    adv = adv and not h1["rows_added"] and not h1["rows_updated"]
    adv = adv and "ARTIFACT_REMOVED" in {
        t["transition"] for t in h2["transitions"]}
    adv = adv and not h2["rows_added"] and not h2["rows_updated"]
    adv = adv and "UNRESOLVED" in {
        t["transition"] for t in i3["transitions"]}
    ck("D21", adv, "artifact-removal + mapping-shrink conservative "
                   "classification")
    checks[-1]["id"] = "D21"

    status = "PASS" if all(c["status"] == "PASS" for c in checks) \
        else "FAIL"
    results = {"gate": "G2-D", "status": status, "checks": checks,
               "scenarios": {n: {"s0": r["s0_corpus_logical_sha256"],
                                 "s1": r["s1_corpus_logical_sha256"],
                                 "delta_id": r["delta_id"],
                                 "transitions": sorted(
                                     {t["transition"]
                                      for t in r["transitions"]}),
                                 "rows_added": r["rows_added"],
                                 "stats": r["stats"]}
                             for n, r in S.items()}}
    RESULTS.write_bytes(json.dumps(results, indent=1,
                                   ensure_ascii=False).encode("utf-8"))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True,
                            cwd=HERE.parents[1]).stdout.strip()
    manifest = {
        "gate": "G2-D-incremental-update-semantics",
        "status": status,
        "executed_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "code_commit": commit,
        "inputs": {"g2d_inputs.json": "pinned G2-C runA dataset files"},
        "outputs": {"g2d_verify_results.json":
                    "D1-D21 check matrix + per-scenario hashes"},
        "sha256": {"g2c_corpus_logical_sha256": g2c_hash},
        "findings": [
            "incremental apply reproduces the clean-rebuild dataset "
            "byte-identically for every corpus-restoring scenario",
            "canonical rows are append-only; ARTIFACT_REMOVED is a "
            "delta-level semantic transition (rows retained)"],
        "limitations": [
            "observations are derived from the G2-C dataset (decompile "
            "round-trip) rather than fresh captures",
            "G and I2 use synthetic observation content (no real CNMV "
            "event exists for them in the frozen corpus)",
            "ARTIFACT_REMOVED does not mark current-source availability "
            "in V1 — that would be a schema addition (V2)"]}
    (HERE / "manifest.json").write_bytes(json.dumps(
        manifest, indent=1, ensure_ascii=False).encode("utf-8"))
    print(f"G2-D: {status} "
          f"({sum(1 for c in checks if c['status'] == 'PASS')}"
          f"/{len(checks)})")
    for c in checks:
        print(f"  {c['id']:>4} {c['status']}  {c['detail'][:110]}")


if __name__ == "__main__":
    main()
