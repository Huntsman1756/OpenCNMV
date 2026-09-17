"""G2-D build: pin-verify the G2-C dataset, decompile it into canonical
observation documents, carve scenario base states, and materialize
independent oracles.

Writes _out/scen/<X>/{S0/v1, O1.json, oracle/v1, spec.json} and
_out/obs/<filing>.json. Nothing here touches the network.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import g2d_common as C  # noqa: E402
from opencnmv.provenance.hashes import artifact_set_id, sha256_bytes  # noqa: E402

FID_B = "cnmv:ipp:2026103709"          # IBE H1-2026 (IPP)
FID_C = "cnmv:ifa:20515"               # IBE FY2024 (es-only + en fallback)
FID_D = "cnmv:ifa:20448"               # BBVA FY2024 (real es+en)
FID_E = "cnmv:ifa:20484"               # TELEFONICA lifecycle fixture
FID_G = "cnmv:ipp:2026103709"          # IPP payload-change host
FID_H = "cnmv:ipp:2026103709"          # artifact-removal host
FID_I = "cnmv:ifa:20854"               # BBVA FY2025 (mixed verdicts)

EV_0302 = FID_E + "#evt:2025-02-28"    # language-silent event (F)
EV_0313 = FID_E + "#evt:2025-03-13"    # EN_ONLY_REPLACED event (E)


def pin_verify() -> dict:
    """Re-hash the pinned G2-C inputs; abort on any mismatch."""
    spec = C.load_json(C.HERE / "g2d_inputs.json")
    bad = []
    for name, meta in spec["files"].items():
        p = C.REPO / meta["path"]
        if not p.is_file():
            bad.append(f"{name}: missing")
            continue
        if sha256_bytes(p.read_bytes()) != meta["sha256"]:
            bad.append(f"{name}: sha256 mismatch")
    if bad:
        raise SystemExit("input pin violations: " + "; ".join(bad))
    return spec


def write_obs(path: Path, doc: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    from opencnmv.serialize import write_canonical
    write_canonical(doc, path)


def synth_artifact(tag: str, role: str) -> dict:
    sha = hashlib.sha256(f"g2d:{tag}".encode()).hexdigest()
    return {"artifact_id": f"sha256:{sha}", "role": role,
            "sha256": sha, "bytes": 4096, "media_type": "text/xml",
            "source_url": None, "package_lang_tag": "es"}


def build():
    spec = pin_verify()
    tables = C.load_tables(C.G2C_DS)
    obs = C.decompile(tables)
    print(f"decompiled {len(obs)} filing observations")

    # persist one canonical observation doc per filing (evidence of the
    # decompile; also the O1 payload for replay-style scenarios)
    obs_dir = C.OUT / "obs"
    for fid, entry in sorted(obs.items()):
        write_obs(obs_dir / f"{fid.replace(':', '_')}.json",
                  C.obs_doc([entry], f"obs:decompiled:{fid}"))

    def scen_dir(name: str) -> Path:
        d = C.OUT / "scen" / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    results: dict[str, dict] = {}

    def emit(name: str, s0_tables, o1: dict, spec_extra: dict,
             oracle_obs: list[dict] | str | None):
        d = scen_dir(name)
        man0 = C.write_dataset(d / "S0" / "v1", s0_tables,
                               inputs={"carved_from": "g2c_runA",
                                       "scenario": name})
        write_obs(d / "O1.json", o1)
        spec_out = {"scenario": name,
                    "s0_corpus_logical_sha256":
                        man0["corpus_logical_sha256"],
                    "observation_sha256": o1["observation_sha256"],
                    **spec_extra}
        if oracle_obs == "g2c":
            spec_out["oracle"] = "g2c_runA"
        elif oracle_obs in (None, "self"):
            spec_out["oracle"] = "self"
        else:
            oman = C.write_dataset(d / "oracle" / "v1",
                                   C.oracle_materialize(oracle_obs),
                                   inputs={"oracle": "obs-union",
                                           "scenario": name})
            spec_out["oracle"] = "built"
            spec_out["oracle_corpus_logical_sha256"] = \
                oman["corpus_logical_sha256"]
        write_obs(d / "spec.json", spec_out)
        results[name] = spec_out
        print(f"[{name}] S0={man0['corpus_logical_sha256'][:12]} "
              f"oracle={spec_out['oracle']}")

    all_obs = [C.obs_doc([e], f"obs:decompiled:{fid}")
               for fid, e in sorted(obs.items())]

    # ---- A: NO_CHANGE -------------------------------------------------
    # complete re-observation of one filing (no states) + identical
    # resubmission of one parsed state -> pure NO_CHANGE
    e_a1 = json.loads(json.dumps(obs["cnmv:ifa:20509"]))   # SAN FY2024
    e_a1.pop("states", None)
    emit("A", tables, C.obs_doc([e_a1, obs[FID_B]], "obs:A-replay"),
         {"filings": ["cnmv:ifa:20509", FID_B]}, "g2c")

    # ---- B: NEW_FILING ------------------------------------------------
    emit("B", C.carve_filing(tables, FID_B),
         C.obs_doc([obs[FID_B]], "obs:B-new-filing"),
         {"filings": [FID_B]}, "g2c")

    # ---- C: UI fallback creates no variant ----------------------------
    e_c = json.loads(json.dumps(obs[FID_C]))
    e_c.pop("states", None)
    emit("C1", tables, C.obs_doc([e_c], "obs:C-fallback-replay"),
         {"filings": [FID_C], "expect": ["NO_CHANGE"]}, "g2c")
    e_c2 = json.loads(json.dumps(e_c))
    e_c2["filing"]["view_resolutions"].append({
        "requested_ui_language": "fr",
        "resolved_variant_id": FID_C + "#es",
        "resolution_mode": "FALLBACK_TO_ES"})
    emit("C2", tables, C.obs_doc([e_c2], "obs:C-fallback-new-view"),
         {"filings": [FID_C],
          "expect": ["VIEW_RESOLUTION_RECORDED"],
          "forbid": ["NEW_SUBMISSION_VARIANT"]},
         all_obs + [C.obs_doc([e_c2], "obs:C2")])

    # ---- D: new real language variant ---------------------------------
    vid_en = FID_D + "#en"
    s0_d = C.deep_tables(tables)
    s0_d["submission_variant"] = [r for r in s0_d["submission_variant"]
                                  if r["variant_id"] != vid_en]
    s0_d["variant_version"] = [r for r in s0_d["variant_version"]
                               if r["variant_id"] != vid_en]
    s0_d["view_resolution"] = [r for r in s0_d["view_resolution"]
                               if not (r["filing_id"] == FID_D and
                                       r["requested_ui_language"] == "en")]
    s0_d["extension_mapping"] = [r for r in s0_d["extension_mapping"]
                                 if r["filing_id"] != FID_D]
    s0_d["artifact"] = [r for r in s0_d["artifact"]
                        if not r["owner_id"].startswith(vid_en)]
    en_fids = {r["fact_id"] for r in s0_d["facts"]
               if r["variant_version_id"].startswith(vid_en)}
    s0_d["facts"] = [r for r in s0_d["facts"]
                     if not r["variant_version_id"].startswith(vid_en)]
    s0_d["fact_dimension"] = [r for r in s0_d["fact_dimension"]
                              if r["fact_id"] not in en_fids]
    s0_d["provenance"] = [r for r in s0_d["provenance"]
                          if r["state_id"] != "BBVA-FY2024-en"]
    emit("D", s0_d, C.obs_doc([obs[FID_D]], "obs:D-new-variant"),
         {"filings": [FID_D],
          "expect": ["NEW_SUBMISSION_VARIANT", "NEW_VARIANT_VERSION",
                     "FACT_ADDED", "EXTENSION_MAPPING_ADDED",
                     "VIEW_RESOLUTION_RECORDED"]}, "g2c")

    # ---- E: variant-scoped replacement (TEF EN_ONLY) ------------------
    vv2 = FID_E + "#en#v2"
    s0_e = C.deep_tables(tables)
    s0_e["variant_version"] = [r for r in s0_e["variant_version"]
                               if r["variant_version_id"] != vv2]
    s0_e["version_event"] = [r for r in s0_e["version_event"]
                             if r["event_id"] != EV_0313]
    s0_e["event_affects"] = [r for r in s0_e["event_affects"]
                             if r["event_id"] != EV_0313]
    s0_e["artifact"] = [r for r in s0_e["artifact"]
                        if r["owner_id"] not in (vv2, EV_0313)]
    emit("E", s0_e, C.obs_doc([obs[FID_E]], "obs:E-en-replace"),
         {"filings": [FID_E],
          "expect": ["NEW_VERSION_EVENT", "VARIANT_SCOPED_VERSION_EVENT",
                     "NEW_VARIANT_VERSION"],
          "must_not_touch_variant": FID_E + "#es"}, "g2c")

    # ---- F: unobservable scope (TEF 28/02) -----------------------------
    s0_f = C.deep_tables(tables)
    s0_f["version_event"] = [r for r in s0_f["version_event"]
                             if r["event_id"] != EV_0302]
    s0_f["event_affects"] = [r for r in s0_f["event_affects"]
                             if r["event_id"] != EV_0302]
    s0_f["artifact"] = [r for r in s0_f["artifact"]
                        if r["owner_id"] != EV_0302]
    # the es v1 version was created_by the carved event: S0 records it
    # before the event is discovered -> created_by backfilled via
    # rows_updated when the event arrives
    for r in s0_f["variant_version"]:
        if r["created_by_event_id"] == EV_0302:
            r["created_by_event_id"] = None
    emit("F", s0_f, C.obs_doc([obs[FID_E]], "obs:F-scope-unknown"),
         {"filings": [FID_E],
          "expect": ["NEW_VERSION_EVENT",
                     "FILING_SCOPE_NOT_OBSERVABLE"],
          "forbid": ["NEW_VARIANT_VERSION",
                     "VARIANT_SCOPED_VERSION_EVENT"],
          "expect_updates": {"variant_version": 1}}, "g2c")

    # ---- G: changed fact payload under same structural identity -------
    e_g = json.loads(json.dumps(obs[FID_G]))
    fxg = e_g["filing"]
    syn_art = synth_artifact("scenG-fv2-package", "IPP_XBRL")
    fxg["filing_versions"].append({
        "filing_version_id": FID_G + "#nreg:2026109999",
        "source_nreg": "2026109999", "filed_at": "2026-08-01",
        "submission_kind": "SUBSTITUTION",
        "artifacts": [syn_art]})
    fxg["submission_variants"][0]["variant_versions"].append({
        "variant_version_id": FID_G + "#es#v2",
        "variant_id": FID_G + "#es", "observed": True,
        "artifact_set_id": artifact_set_id([syn_art]),
        "artifacts": [],
        "created_by_event_id": None,
        "supersedes_variant_version_id": FID_G + "#es#v1"})
    st_g = json.loads(json.dumps(e_g["states"][0]))
    st_g["state_id"] = "IBE-H1-2026-R1"
    st_g["variant_version_id"] = FID_G + "#es#v2"
    st_g["facts"][0]["value_sha256"] = "9" * 64
    st_g["facts"][0]["xValue_sha256"] = "8" * 64
    st_g["facts"][0]["value_preview"] = "99999999"
    st_g["provenance"] = dict(st_g["provenance"], sha256=syn_art["sha256"],
                            artifact_id=syn_art["artifact_id"])
    e_g["states"] = [st_g]
    emit("G", tables, C.obs_doc([e_g], "obs:G-payload-change"),
         {"filings": [FID_G],
          "expect": ["NEW_FILING_VERSION", "NEW_VARIANT_VERSION",
                     "FACT_PAYLOAD_CHANGED"]},
         all_obs + [C.obs_doc([e_g], "obs:G2")])

    # ---- H: artifact removal -------------------------------------------
    e_h = json.loads(json.dumps(obs[FID_H]))
    fv0 = e_h["filing"]["filing_versions"][0]
    removed_art = fv0["artifacts"].pop(0)
    e_h.pop("states", None)
    emit("H1", tables, C.obs_doc([e_h], "obs:H-artifact-gone"),
         {"filings": [FID_H], "expect": ["UNRESOLVED"],
          "replay_expect": "SAME_UNRESOLVED"}, "self")
    e_h2 = json.loads(json.dumps(e_h))
    e_h2["artifact_dispositions"] = {
        removed_art["artifact_id"]: {"status": "REMOVED_CONFIRMED",
                                     "evidence": "g2d:scenario-H"}}
    emit("H2", tables, C.obs_doc([e_h2], "obs:H-artifact-removed"),
         {"filings": [FID_H], "expect": ["ARTIFACT_REMOVED"],
          "forbid_row_ops": True,
          "replay_expect": "SAME_TRANSITION"}, "self")

    # ---- I: extension mapping evolution --------------------------------
    s0_i = C.deep_tables(tables)
    s0_i["extension_mapping"] = [r for r in s0_i["extension_mapping"]
                                 if r["filing_id"] != FID_I]
    emit("I1", s0_i, C.obs_doc([obs[FID_I]], "obs:I-mappings-added"),
         {"filings": [FID_I],
          "expect": ["EXTENSION_MAPPING_ADDED"]}, "g2c")

    e_i = json.loads(json.dumps(obs[FID_I]))
    recs = e_i["extension_mapping_files"][0]["records"]
    amb = next(i for i, r in enumerate(recs) if r["verdict"] == "AMBIGUOUS")
    prov = next(i for i, r in enumerate(recs)
                if r["verdict"] == "PROVEN_EQUIVALENT")
    recs[amb]["verdict"] = "PROVEN_EQUIVALENT"        # promotion w/ verdict
    recs[prov]["verdict"] = "AMBIGUOUS"               # demotion
    amb2 = next(i for i, r in enumerate(recs)
                if r["verdict"] == "AMBIGUOUS")
    recs[amb2]["rewrites_identity"] = True            # adversarial claim
    emit("I2", tables, C.obs_doc([e_i], "obs:I-mappings-evolved"),
         {"filings": [FID_I],
          "expect": ["EXTENSION_MAPPING_CHANGED"],
          "changed_ordinals": {"promoted": amb, "demoted": prov,
                               "adversarial": amb2}},
         all_obs + [C.obs_doc([e_i], "obs:I2")])

    e_i3 = json.loads(json.dumps(obs[FID_I]))
    e_i3["extension_mapping_files"][0]["records"].pop()   # missing record
    emit("I3", tables, C.obs_doc([e_i3], "obs:I-mapping-shrunk"),
         {"filings": [FID_I], "expect": ["UNRESOLVED"],
          "replay_expect": "SAME_UNRESOLVED"}, "self")

    (C.OUT / "build_results.json").write_bytes(json.dumps(
        {"g2c_corpus_logical_sha256": spec["g2c_corpus_logical_sha256"],
         "scenarios": results}, indent=1, ensure_ascii=False).encode(
            "utf-8"))
    print("build complete")


if __name__ == "__main__":
    build()
