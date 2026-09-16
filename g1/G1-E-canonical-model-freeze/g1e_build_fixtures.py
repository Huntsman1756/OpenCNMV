# G1-E — rebuilds the four canonical fixtures deterministically from the
# preserved G1 evidence (no network):
#   fixtures/ibe_fy2024.json   single variant + en UI fallback      (I1)
#   fixtures/bbva_fy2024.json  dual variant + DIVERGENT fact pair   (I5)
#   fixtures/san_fy2024.json   dual variant + PROVEN ext mappings   (I9)
#   fixtures/tef_20484.json    variant-level lifecycle events       (I2/I7/I8)
from __future__ import annotations

import hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from canonical_model import CanonicalFiling  # noqa: E402

G1A = json.loads((ROOT / "g1/G1-A-oam-variant-discovery/g1a_results.json")
                 .read_text(encoding="utf-8"))
INV = json.loads((ROOT / "g1/G1-B-dual-language-capture/evidence/capture/"
                 "runA/variant_inventory.json").read_text(encoding="utf-8"))
G1D = json.loads((ROOT / "g1/G1-D-variant-lifecycle-falsification/"
                 "g1d_results.json").read_text(encoding="utf-8"))
TEF = json.loads((ROOT / "g1/G1-D-variant-lifecycle-falsification/"
                 "g1d_tef20484.json").read_text(encoding="utf-8"))

LEI = {"SAN": "5493006QMFDDMYWIAM13", "BBVA": "K8MS7FD7N5Z2WQ51AZ71",
       "IBE": "5QK37QC7NWOJ8D7WVQ45", "TELEFONICA": "549300EEJH4FEPDBBR25"}
NAME = {"SAN": "BANCO SANTANDER, S.A.", "BBVA": "BANCO BILBAO VIZCAYA "
        "ARGENTARIA, S.A.", "IBE": "IBERDROLA, S.A.",
        "TELEFONICA": "TELEFONICA, S.A."}


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def artifact_set_id(artifacts):
    """G1-B identity: sha256 over canonical sort of (role, sha256) pairs."""
    pairs = sorted([[a["role"], a["sha256"]] for a in artifacts])
    return hashlib.sha256(canon(pairs).encode("utf-8")).hexdigest()


def inv_filing(issuer, fy):
    return next(f for f in INV["filings"]
                if f["issuer"] == issuer and f["fy"] == fy)


def g1a_row(issuer, fy):
    return next(r for r in G1A["results"]
                if r["issuer"] == issuer and r["fy"] == fy)


def nreg_of(row):
    m = re.search(r"nreg=(\d+)", row["registry_row"]["infadicion"][0]
                  .replace("&amp;", "&"))
    return m.group(1) if m else None


def build_corpus_fixture(issuer, fy):
    f = inv_filing(issuer, fy)
    reg = f["registro"]
    fid = f"cnmv:ifa:{reg}"
    a1 = g1a_row(issuer, fy)
    nreg = nreg_of(f["views"]["es"])
    out = {
        "filing_id": fid,
        "issuer": {"denomination": NAME[issuer], "lei": LEI[issuer]},
        "registro_oficial": reg,
        "family": "ESEF_IFA",
        "period_end": a1["cells_period_end"] if "cells_period_end" in a1
        else f["views"]["es"]["registry_row"]["cells"][1],
        "filing_versions": [{
            "filing_version_id": f"{fid}#nreg:{nreg}",
            "source_nreg": nreg,
            "filed_at": None,
            "submission_kind": "ORIGINAL_SUBMISSION"}],
        "submission_variants": [],
        "view_resolutions": [],
        "version_events": [{
            "event_id": f"{fid}#evt:formulacion",
            "event_date": f["views"]["es"]["registry_row"]["cells"][2],
            "event_type": "CERTIFICATE",
            "source_label": "formulación y firma",
            "source_nreg": nreg,
            "evidence_artifact_id": None,
            "scope_status": "NOT_A_VERSION_TRANSITION",
            "affects": []}],
        "extension_mappings": []}
    for lang in ("es", "en"):
        v = f["views"][lang]
        if v["resolution_mode"] != "SUBMITTED_VARIANT":
            continue
        vid = f"{fid}#{lang}"
        arts = [{"artifact_id": f"sha256:{v['package']['sha256']}",
                 "role": "ESEF_PACKAGE_ZIP_XBRL",
                 "sha256": v["package"]["sha256"],
                 "bytes": v["package"]["bytes"],
                 "media_type": v["package"]["content_type"],
                 "package_lang_tag": lang}]
        out["submission_variants"].append({
            "variant_id": vid, "filing_id": fid,
            "submission_language": lang,
            "variant_versions": [{
                "variant_version_id": f"{vid}#v1",
                "variant_id": vid, "observed": True,
                "artifact_set_id": v["variant_artifact_set_id"],
                "artifacts": arts,
                "created_by_event_id": f"{fid}#evt:formulacion",
                "supersedes_variant_version_id": None}]})
    for lang in ("es", "en"):
        v = f["views"][lang]
        resolved_lang = v["resolved_submission_language"]
        out["view_resolutions"].append({
            "requested_ui_language": lang,
            "resolved_variant_id": f"{fid}#{resolved_lang}",
            "resolution_mode": v["resolution_mode"]})
    return out


def add_bbva_divergence(fx):
    p = (ROOT / "g1/G1-B-dual-language-capture/evidence/compare/"
         "BBVA-FY2024.comparison.jsonl")
    rec = next(json.loads(l) for l in p.read_text(encoding="utf-8")
               .splitlines()
               if json.loads(l).get("class") == "DIVERGENT_SUBMISSION_FACT")
    fx["fact_examples"] = [{
        "note": "I5: same structural key (sans language), divergent payload",
        "comparison_class": rec["class"],
        "key": rec["key"],
        "es": {"variant_version_id":
               f"{fx['filing_id']}#es#v1", "lang": rec["es"]["lang"],
               "value": rec["es"]["value"], "decimals": rec["es"]["decimals"],
               "value_sha256": rec["es"]["value_sha256"]},
        "en": {"variant_version_id":
               f"{fx['filing_id']}#en#v1", "lang": rec["en"]["lang"],
               "value": rec["en"]["value"], "decimals": rec["en"]["decimals"],
               "value_sha256": rec["en"]["value_sha256"]}}]
    return fx


def add_san_mappings(fx):
    p = (ROOT / "g1/G1-C-extension-variant-identity/evidence/mapping/"
         "SAN-FY2024.mapping.json")
    recs = json.loads(p.read_text(encoding="utf-8"))
    recs = recs if isinstance(recs, list) else recs.get(
        "records", recs.get("mappings", []))
    counts = {}
    for r in recs:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    fid = fx["filing_id"]
    proven = [r for r in recs if r["verdict"] == "PROVEN_EQUIVALENT"]
    example = proven[0]
    fx["extension_mappings"] = [{
        "pair_id": example["pair_id"], "filing_id": fid,
        "source_variant_id": f"{fid}#es",
        "target_variant_id": f"{fid}#en",
        "source_qname": example["source_qname"],
        "target_qname": example["target_qname"],
        "mapping_type": example["mapping_type"],
        "verdict": example["verdict"],
        "evidence": example["evidence"]}]
    fx["extension_mapping_summary"] = counts
    return fx


def build_tef():
    fid = "cnmv:ifa:20484"
    fx = {
        "filing_id": fid,
        "issuer": {"denomination": NAME["TELEFONICA"],
                   "lei": LEI["TELEFONICA"]},
        "registro_oficial": "20484", "family": "ESEF_IFA",
        "period_end": "2024-12-31",
        "filing_versions": [
            {"filing_version_id": f"{fid}#nreg:2025030764",
             "source_nreg": "2025030764", "filed_at": "2025-02-27",
             "submission_kind": "ORIGINAL_SUBMISSION"},
            {"filing_version_id": f"{fid}#nreg:2025031622",
             "source_nreg": "2025031622", "filed_at": "2025-02-28",
             "submission_kind": "SUBSTITUTION"}],
        "submission_variants": [], "view_resolutions": [],
        "version_events": [], "extension_mappings": []}
    # variants: es has 1 observed version; en has 2 (v1 unobserved/superseded)
    for lang in ("es", "en"):
        vid = f"{fid}#{lang}"
        docs = TEF["phase1"][lang]["docs"]
        role_map = {0: "IXBRL_INDIVIDUAL", 1: "IXBRL_CONSOLIDATED"}
        arts = [{"artifact_id": f"sha256:{d['sha256']}",
                 "role": ("ESEF_PACKAGE_ZIP_XBRL"
                          if d["kind"] == "ESEF_PACKAGE_ZIP"
                          else role_map[d["token_idx"]]),
                 "sha256": d["sha256"], "bytes": d["bytes"],
                 "media_type": d["ctype"],
                 "package_lang_tag": d.get("package_lang_tag")}
                for d in docs]
        vvs = []
        if lang == "en":
            vvs.append({"variant_version_id": f"{vid}#v1",
                        "variant_id": vid, "observed": False,
                        "artifact_set_id": None, "artifacts": [],
                        "created_by_event_id": None,
                        "supersedes_variant_version_id": None})
        vvs.append({"variant_version_id": f"{vid}#v2" if lang == "en"
                    else f"{vid}#v1",
                    "variant_id": vid, "observed": True,
                    "artifact_set_id": artifact_set_id(arts),
                    "artifacts": arts,
                    "created_by_event_id": f"{fid}#evt:2025-03-13"
                    if lang == "en" else f"{fid}#evt:2025-02-28",
                    "supersedes_variant_version_id": f"{vid}#v1"
                    if lang == "en" else None})
        fx["submission_variants"].append({
            "variant_id": vid, "filing_id": fid,
            "submission_language": lang, "variant_versions": vvs})
        fx["view_resolutions"].append({
            "requested_ui_language": lang,
            "resolved_variant_id": vid,
            "resolution_mode": "SUBMITTED_VARIANT"})
    ev_docs = {d["file"]: d for d in TEF["phase2"]["es"]["docs"]}
    e3 = ev_docs["doc-TEF-20484-es-e3-0.pdf"]
    e1 = ev_docs["doc-TEF-20484-es-e1-0.pdf"]
    ev = G1D["tef_20484"]["events"]
    fx["version_events"] = [
        {"event_id": f"{fid}#evt:2025-02-28",
         "event_date": "2025-02-28", "event_type": "SUBSTITUTION",
         "source_label": "Certificado del secretario del consejo sobre la "
                         "sustitución del informe financiero anual",
         "source_nreg": "2025031622",
         "evidence_artifact_id": f"sha256:{e3['sha256']}",
         "scope_status": ev[0]["scope"],
         "affects": [{"variant_id": None,
                      "affected_component_scope": "NOT_IDENTIFIED",
                      "component_description":
                          "reason scoped to Cuentas Anuales Individuales; "
                          "silent on language",
                      "before_variant_version_id": None,
                      "after_variant_version_id": None,
                      "scope_basis": f"sha256:{e3['sha256']}"}]},
        {"event_id": f"{fid}#evt:2025-03-13",
         "event_date": "2025-03-13", "event_type": "SUBSTITUTION",
         "source_label": "Otra información complementaria (Otros) "
                         "[label; doc content is a substitution cert]",
         "source_nreg": None,
         "evidence_artifact_id": f"sha256:{e1['sha256']}",
         "scope_status": ev[1]["scope"],
         "affects": [{"variant_id": f"{fid}#en",
                      "affected_component_scope": "SOURCE_DESCRIBED",
                      "component_description":
                          "versión en inglés publicada de los Estados "
                          "Financieros Consolidados y respectivo Informe de "
                          "Gestión",
                      "before_variant_version_id": f"{fid}#en#v1",
                      "after_variant_version_id": f"{fid}#en#v2",
                      "scope_basis": f"sha256:{e1['sha256']}"}]}]
    return fx


def main():
    fxdir = HERE / "fixtures"
    fxdir.mkdir(exist_ok=True)
    fixtures = {
        "ibe_fy2024": build_corpus_fixture("IBE", "FY2024"),
        "bbva_fy2024": add_bbva_divergence(
            build_corpus_fixture("BBVA", "FY2024")),
        "san_fy2024": add_san_mappings(build_corpus_fixture("SAN", "FY2024")),
        "tef_20484": build_tef()}
    for name, fx in fixtures.items():
        CanonicalFiling.model_validate(fx)      # fail fast on bad fixture
        (fxdir / f"{name}.json").write_bytes(
            json.dumps(fx, indent=1, ensure_ascii=False).encode("utf-8"))
        print("wrote", name)
    # export JSON Schema (bytes, LF)
    (HERE / "canonical_model_v1.schema.json").write_bytes(
        json.dumps(CanonicalFiling.model_json_schema(), indent=1,
                   ensure_ascii=False).encode("utf-8"))
    print("wrote canonical_model_v1.schema.json")


if __name__ == "__main__":
    main()
