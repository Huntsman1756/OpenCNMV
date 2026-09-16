# G2-A — rebuilds the four frozen G1-E fixtures through the durable core
# (src/opencnmv), offline, from sha256-pinned preserved evidence.
#
# Guards active during rebuild:
#   - socket deny-all sentinel (no network)
#   - meta_path import blocker for any module under g0-r/ or g1/
#   - input evidence verified against g2a_inputs.json pins before use
from __future__ import annotations

import importlib.abc
import json, socket, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "_out"

# ---- guards -------------------------------------------------------------
_NET_CALLS = []


def _deny(*a, **k):
    _NET_CALLS.append(a)
    raise RuntimeError("network access denied during fixture rebuild")


socket.socket.connect = _deny            # type: ignore[attr-defined]
socket.create_connection = _deny         # type: ignore[attr-defined]
socket.getaddrinfo = _deny               # type: ignore[attr-defined]


class _GateCodeBlocker(importlib.abc.MetaPathFinder):
    """Refuse to import any module file living under g0-r/ or g1/ — the
    durable core may not reuse gate scripts as code (evidence files are
    data inputs, read by path, which remains allowed)."""

    def find_spec(self, name, path=None, target=None):
        try:
            spec = importlib.machinery.PathFinder.find_spec(
                name, path, target)
        except Exception:  # noqa: BLE001
            return None
        if spec and spec.origin:
            p = str(spec.origin).replace("\\", "/")
            if "/g0-r/" in p or "/g1/" in p or p.startswith("g0-r/") \
                    or p.startswith("g1/"):
                raise ImportError(f"gate-code import blocked: {name} "
                                  f"({spec.origin})")
        return None


sys.meta_path.insert(0, _GateCodeBlocker())

sys.path.insert(0, str(ROOT / "src"))

from opencnmv.canonicalize import (events, extension_mapping, filing,  # noqa: E402
                                   variants)
from opencnmv.model import ids  # noqa: E402
from opencnmv.model.canonical import CanonicalFiling  # noqa: E402
from opencnmv.provenance import hashes  # noqa: E402
from opencnmv.serialize import write_canonical  # noqa: E402

LEI = {"SAN": "5493006QMFDDMYWIAM13", "BBVA": "K8MS7FD7N5Z2WQ51AZ71",
       "IBE": "5QK37QC7NWOJ8D7WVQ45", "TELEFONICA": "549300EEJH4FEPDBBR25"}
NAME = {"SAN": "BANCO SANTANDER, S.A.",
        "BBVA": "BANCO BILBAO VIZCAYA ARGENTARIA, S.A.",
        "IBE": "IBERDROLA, S.A.", "TELEFONICA": "TELEFONICA, S.A."}


def load_inputs():
    pins = json.loads((HERE / "g2a_inputs.json").read_text(encoding="utf-8"))
    data = {}
    for key, p in pins.items():
        fp = ROOT / p["path"]
        body = fp.read_bytes()
        assert hashes.sha256_bytes(body) == p["sha256"], \
            f"input pin mismatch: {p['path']}"
        data[key] = body
    return {k: json.loads(v) if not k.endswith("comparison") else v
            for k, v in data.items()}


def inv_filing(inv, issuer, fy):
    return next(f for f in inv["filings"]
                if f["issuer"] == issuer and f["fy"] == fy)


def build_corpus_fixture(data, issuer, fy):
    f = inv_filing(data["variant_inventory"], issuer, fy)
    reg = f["registro"]
    fid = ids.filing_id(reg)
    nreg = nreg_of(f["views"]["es"])
    fx = filing.new_filing(
        reg, {"denomination": NAME[issuer], "lei": LEI[issuer]},
        period_end=f["views"]["es"]["registry_row"]["cells"][1])
    fx["filing_versions"].append(filing.filing_version(
        fid, nreg, submission_kind="ORIGINAL_SUBMISSION"))
    fx["version_events"].append(events.event(
        fid, "formulacion", "CERTIFICATE",
        event_date=f["views"]["es"]["registry_row"]["cells"][2],
        source_label="formulación y firma", source_nreg=nreg,
        scope_status="NOT_A_VERSION_TRANSITION"))
    for lang in ("es", "en"):
        v = f["views"][lang]
        if v["resolution_mode"] != "SUBMITTED_VARIANT":
            continue
        vid = ids.variant_id(fid, lang)
        sv = variants.variant(fid, lang)
        sv["variant_versions"].append(variants.variant_version(
            vid, 1, observed=True,
            artifact_set_id=v["variant_artifact_set_id"],
            artifacts=[filing.artifact(
                "ESEF_PACKAGE_ZIP_XBRL", v["package"]["sha256"],
                bytes_=v["package"]["bytes"],
                media_type=v["package"]["content_type"],
                package_lang_tag=lang)],
            created_by_event_id=ids.event_id(fid, "formulacion")))
        fx["submission_variants"].append(sv)
    for lang in ("es", "en"):
        v = f["views"][lang]
        fx["view_resolutions"].append(variants.view_resolution(
            fid, lang, v["resolved_submission_language"],
            v["resolution_mode"]))
    return fx


def nreg_of(view):
    import re
    m = re.search(r"nreg=(\d+)",
                  view["registry_row"]["infadicion"][0].replace("&amp;", "&"))
    return m.group(1) if m else None


def build_bbva(data):
    fx = build_corpus_fixture(data, "BBVA", "FY2024")
    rec = next(json.loads(l) for l in
               data["bbva_comparison"].decode("utf-8").splitlines()
               if json.loads(l).get("class") == "DIVERGENT_SUBMISSION_FACT")
    fid = fx["filing_id"]
    fx["fact_examples"] = [{
        "note": "I5: same structural key (sans language), divergent payload",
        "comparison_class": rec["class"], "key": rec["key"],
        "es": {"variant_version_id": ids.variant_version_id(
                   ids.variant_id(fid, "es"), 1),
               "lang": rec["es"]["lang"], "value": rec["es"]["value"],
               "decimals": rec["es"]["decimals"],
               "value_sha256": rec["es"]["value_sha256"]},
        "en": {"variant_version_id": ids.variant_version_id(
                   ids.variant_id(fid, "en"), 1),
               "lang": rec["en"]["lang"], "value": rec["en"]["value"],
               "decimals": rec["en"]["decimals"],
               "value_sha256": rec["en"]["value_sha256"]}}]
    return fx


def build_san(data):
    fx = build_corpus_fixture(data, "SAN", "FY2024")
    recs = data["san_mapping"]
    recs = recs if isinstance(recs, list) else recs.get(
        "records", recs.get("mappings", []))
    counts = {}
    for r in recs:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    fid = fx["filing_id"]
    example = next(r for r in recs
                   if extension_mapping.rewrites_identity(r))
    fx["extension_mappings"].append(extension_mapping.mapping_record(
        fid, "es", "en", example))
    fx["extension_mapping_summary"] = counts
    return fx


def build_tef(data):
    g1d, tef = data["g1d_results"], data["g1d_tef20484"]
    fid = ids.filing_id("20484")
    fx = filing.new_filing(
        "20484", {"denomination": NAME["TELEFONICA"],
                  "lei": LEI["TELEFONICA"]},
        period_end="2024-12-31")
    fx["filing_versions"] = [
        filing.filing_version(fid, "2025030764", "2025-02-27",
                              "ORIGINAL_SUBMISSION"),
        filing.filing_version(fid, "2025031622", "2025-02-28",
                              "SUBSTITUTION")]
    ev = g1d["tef_20484"]["events"]
    ev_ids = {"2025-02-28": "2025-02-28", "2025-03-13": "2025-03-13"}
    for lang in ("es", "en"):
        vid = ids.variant_id(fid, lang)
        docs = tef["phase1"][lang]["docs"]
        role_map = {0: "IXBRL_INDIVIDUAL", 1: "IXBRL_CONSOLIDATED"}
        arts = [filing.artifact(
            "ESEF_PACKAGE_ZIP_XBRL" if d["kind"] == "ESEF_PACKAGE_ZIP"
            else role_map[d["token_idx"]],
            d["sha256"], bytes_=d["bytes"], media_type=d["ctype"],
            package_lang_tag=d.get("package_lang_tag"))
            for d in docs]
        sv = variants.variant(fid, lang)
        if lang == "en":
            sv["variant_versions"].append(variants.variant_version(
                vid, 1, observed=False))
        sv["variant_versions"].append(variants.variant_version(
            vid, 2 if lang == "en" else 1, observed=True,
            artifact_set_id=hashes.artifact_set_id(arts),
            artifacts=arts,
            created_by_event_id=ids.event_id(
                fid, ev_ids["2025-03-13"] if lang == "en"
                else ev_ids["2025-02-28"]),
            supersedes=ids.variant_version_id(vid, 1)
            if lang == "en" else None))
        fx["submission_variants"].append(sv)
        fx["view_resolutions"].append(variants.view_resolution(
            fid, lang, lang, "SUBMITTED_VARIANT"))
    ev_docs = {d["file"]: d for d in tef["phase2"]["es"]["docs"]}
    e3, e1 = (ev_docs["doc-TEF-20484-es-e3-0.pdf"],
              ev_docs["doc-TEF-20484-es-e1-0.pdf"])
    fx["version_events"] = [
        events.event(
            fid, "2025-02-28", "SUBSTITUTION", event_date="2025-02-28",
            source_label="Certificado del secretario del consejo sobre la "
                         "sustitución del informe financiero anual",
            source_nreg="2025031622",
            evidence_artifact_id=ids.artifact_id(e3["sha256"]),
            scope_status=ev[0]["scope"],
            affects=[events.affects(
                component_scope="NOT_IDENTIFIED",
                component_description="reason scoped to Cuentas Anuales "
                                      "Individuales; silent on language",
                scope_basis=ids.artifact_id(e3["sha256"]))]),
        events.event(
            fid, "2025-03-13", "SUBSTITUTION", event_date="2025-03-13",
            source_label="Otra información complementaria (Otros) "
                         "[label; doc content is a substitution cert]",
            source_nreg=None,
            evidence_artifact_id=ids.artifact_id(e1["sha256"]),
            scope_status=ev[1]["scope"],
            affects=[events.affects(
                variant_id=ids.variant_id(fid, "en"),
                component_scope="SOURCE_DESCRIBED",
                component_description="versión en inglés publicada de los "
                                      "Estados Financieros Consolidados y "
                                      "respectivo Informe de Gestión",
                before=ids.variant_version_id(ids.variant_id(fid, "en"), 1),
                after=ids.variant_version_id(ids.variant_id(fid, "en"), 2),
                scope_basis=ids.artifact_id(e1["sha256"]))])]
    return fx


def main(out_dir=None):
    out_dir = Path(out_dir) if out_dir else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    data = load_inputs()
    builders = {"ibe_fy2024": lambda: build_corpus_fixture(data, "IBE",
                                                         "FY2024"),
                "bbva_fy2024": lambda: build_bbva(data),
                "san_fy2024": lambda: build_san(data),
                "tef_20484": lambda: build_tef(data)}
    for name, b in builders.items():
        fx = b()
        CanonicalFiling.model_validate(fx)
        write_canonical(fx, out_dir / f"{name}.json")
        print("built", name)
    prov = {"guards": {"socket_denied": True,
                       "gate_code_imports_blocked": True,
                       "network_calls_attempted": len(_NET_CALLS)},
            "inputs": json.loads(
                (HERE / "g2a_inputs.json").read_text(encoding="utf-8"))}
    write_canonical(prov, out_dir / "_provenance.json")
    print("provenance written; network calls attempted:",
          len(_NET_CALLS))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
