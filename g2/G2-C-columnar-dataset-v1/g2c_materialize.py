# G2-C — COLUMNAR_DATASET_V1 materialization orchestrator.
#
# Two runs (PYTHONHASHSEED 17 / 991, fresh output dirs, isolated worker
# env). Per run:
#   1. verify all pinned inputs (g2c_inputs.json + g2b_inputs.json)
#   2. parse all 25 frozen XBRL states through the production path
#      (subprocess workers, socket deny-all, gate-code import blocker)
#   3. assemble canonical filing objects from sha256-pinned evidence
#      through src/opencnmv canonicalize primitives
#   4. decompose objects + fact records into table rows, write Parquet,
#      schema JSON and dataset_manifest.json
#
# Frozen G0/G1/G2 evidence is read as DATA (sha256-pinned inputs /
# regression oracles), never imported as code.
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "_out"
sys.path.insert(0, str(REPO / "src"))
from opencnmv.provenance.hashes import sha256_file, sha256_bytes, artifact_set_id  # noqa: E402
from opencnmv.model import ids                     # noqa: E402
from opencnmv.canonicalize import (events, extension_mapping, filing,  # noqa: E402
                                   variants, facts as xfacts)
from opencnmv.source.cnmv.discovery import parse_listaifi_rows  # noqa: E402
from opencnmv.dataset import tables as dtables      # noqa: E402
from opencnmv.dataset import schema as dschema      # noqa: E402
from opencnmv.dataset import parquetio              # noqa: E402
from opencnmv.dataset import manifest as dmanifest  # noqa: E402
from opencnmv.model.canonical import CanonicalFiling  # noqa: E402
from opencnmv.serialize import write_canonical      # noqa: E402

TAX_DIR = REPO / "g0-r/R10-taxonomy-pinning/evidence"


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def load_inputs():
    pins = load_json(HERE / "g2c_inputs.json")
    data = {}
    for key, p in pins.items():
        fp = REPO / p["path"]
        body = fp.read_bytes()
        assert sha256_bytes(body) == p["sha256"], \
            f"input pin mismatch: {p['path']}"
        data[key] = body
    keep_raw = ("comparison", "listaifi_")
    return {k: (v if k.endswith(keep_raw) or k.startswith("listaifi_")
                else json.loads(v))
            for k, v in data.items()}


def verify_g2b_pins():
    inputs = load_json(HERE.parent / "G2-B-frozen-corpus-rebuild" /
                       "g2b_inputs.json")
    bad = []
    for group in ("artifacts", "taxonomy_packages", "oracles"):
        for key, rec in inputs[group].items():
            p = REPO / rec["path"]
            if not p.is_file() or sha256_file(p).upper() != rec["sha256"]:
                bad.append(key)
    return bad


# ---- isolated parse workers ------------------------------------------------

def isolated_env(run_dir: Path, hashseed: int) -> dict:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(hashseed)
    env["PYTHONIOENCODING"] = "utf-8"
    for var, sub in (("XDG_CONFIG_HOME", "xdg"),
                     ("HOME", "home"), ("USERPROFILE", "home"),
                     ("APPDATA", "appdata"), ("LOCALAPPDATA", "appdata"),
                     ("TEMP", "tmp"), ("TMP", "tmp"), ("TMPDIR", "tmp")):
        d = run_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        env[var] = str(d)
    return env


def run_parse(entry: dict, run_dir: Path, env: dict) -> dict:
    spec = dict(entry)
    spec["out_dir"] = str(run_dir)
    spec["tax_dir"] = str(TAX_DIR)
    spec["artifact"] = str(REPO / entry["artifact"])
    spec_path = run_dir / f"{entry['id']}.spec.json"
    spec_path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(HERE / "g2c_parse_one.py"),
         str(spec_path)],
        env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if r.returncode != 0:
        return {"filing": entry["id"], "status": "WORKER_CRASH",
                "stderr": r.stderr[-2000:]}
    line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}"
    return json.loads(line)


# ---- canonical object assembly (production primitives) ---------------------

def _ddmmyyyy(s: str) -> str:
    d, m, y = s.split("/")
    return f"{y}-{m}-{d}"


def build_esef_filing(data, issuer_key: str, fy: str) -> dict:
    """Same construction as the frozen G1-E corpus fixtures."""
    inv = data["variant_inventory"]
    issuers = data["issuers"]
    f = next(x for x in inv["filings"]
             if x["issuer"] == issuer_key and x["fy"] == fy)
    reg = f["registro"]
    fid = ids.filing_id(reg)
    nreg = nreg_of(f["views"]["es"])
    iss = issuers[issuer_key]
    fx = filing.new_filing(
        reg, {"denomination": iss["denomination"], "lei": iss["lei"]},
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


def build_tef(data) -> dict:
    """Same construction as the frozen tef_20484 fixture."""
    g1d, tef = data["g1d_results"], data["g1d_tef20484"]
    iss = data["issuers"]["TELEFONICA"]
    fid = ids.filing_id("20484")
    fx = filing.new_filing(
        "20484", {"denomination": iss["denomination"], "lei": iss["lei"]},
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
            artifact_set_id=artifact_set_id(arts),
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


def build_ipp_filings(data) -> list[tuple]:
    """15 IPP filings: cnmv:ipp:<nreg>, implicit es variant, artifact on
    filing_version (CANONICAL_MODEL_V1 migration note)."""
    issuers = data["issuers"]
    manifest = data["artifact_manifest"]
    listaifi = {}
    for issuer_key, k in (("SAN", "listaifi_san"), ("BBVA", "listaifi_bbva"),
                          ("IBE", "listaifi_ibe")):
        html = data[k].decode("utf-8", errors="replace")
        for r in parse_listaifi_rows(html):
            listaifi[r["nreg"]] = r
    out = []
    for rec in manifest:
        if rec["family"] != "IPP":
            continue
        # evidence_path encodes issuer + slot: ipp-SAN-I-semestre-de-2024.zip
        name = Path(rec["evidence_path"].replace("\\", "/")).name
        parts = name[:-4].split("-")          # ipp, ISSUER, I|II, semestre, de, YYYY
        issuer_key, half, year = parts[1], parts[2], parts[5]
        nreg = rec["source_registration_no"]
        fid = ids.filing_id(nreg, ids.IPP)
        iss = issuers[issuer_key]
        li = listaifi.get(nreg, {})
        fx = filing.new_filing(
            nreg, {"denomination": iss["denomination"], "nif": iss["nif"],
                   "lei": iss["lei"]},
            period_end=(f"{year}-06-30" if half == "I" else f"{year}-12-31"),
            family="IPP")
        fx["filing_id"] = fid  # new_filing used IFA prefix; correct to ipp:
        fx["filing_versions"] = [dict(
            filing.filing_version(fid, nreg,
                                  _ddmmyyyy(li["published"])
                                  if li.get("published") else None,
                                  "ORIGINAL_SUBMISSION"),
            artifacts=[filing.artifact(
                "IPP_XBRL", rec["sha256"].lower(),
                bytes_=rec["byte_size"], media_type=rec["media_type"],
                source_url=rec["final_url"], package_lang_tag="es")])]
        vid = ids.variant_id(fid, "es")
        sv = variants.variant(fid, "es")
        sv["variant_versions"].append(variants.variant_version(
            vid, 1, observed=True,
            artifact_set_id=artifact_set_id(
                [{"role": "IPP_XBRL", "sha256": rec["sha256"].lower()}]),
            artifacts=[]))
        fx["submission_variants"].append(sv)
        fx["view_resolutions"] = [variants.view_resolution(
            fid, "es", "es", "SUBMITTED_VARIANT")]
        out.append((fx, rec, name))
    out.sort(key=lambda t: t[0]["filing_id"])
    return out


# ---- fact plane --------------------------------------------------------------

def canonical_key_of(rec: dict) -> dict:
    if rec.get("period_start"):
        period = f"{rec['period_start']}/{rec['period_end']}"
    elif rec.get("period_instant"):
        period = rec["period_instant"]
    else:
        period = "forever"
    entity = "|".join(x for x in (rec.get("entity_scheme"),
                                  rec.get("entity")) if x)
    return {"concept": rec["concept"], "entity": entity, "period": period,
            "dimensions": rec.get("dimensions") or {},
            "unit": rec.get("unit"), "language": rec.get("lang")}


# ---- one materialization run -------------------------------------------------

def materialize_run(run_dir: Path, corpus: list[dict], data: dict,
                    filings: dict[str, dict], state_vv: dict[str, str],
                    provenance: dict[str, dict], code_commit: str) -> dict:
    ds_dir = run_dir / "dataset" / "v1"
    ds_dir.mkdir(parents=True, exist_ok=True)
    all_rows: dict[str, list[dict]] = {t: [] for t in dschema.TABLE_ORDER}

    # model layer
    for name in sorted(filings):
        ent = filings[name]
        rows = dtables.filing_rows(ent["fx"], extras=ent["extras"])
        for t, rl in rows.items():
            all_rows[t].extend(rl)
        all_rows["artifact"].extend(ent["extra_artifacts"])

    # extension_mapping: full G1-C record sets
    for key, issuer_fy in (("mapping_san_fy2024", ("SAN", "FY2024")),
                           ("mapping_san_fy2025", ("SAN", "FY2025")),
                           ("mapping_bbva_fy2024", ("BBVA", "FY2024")),
                           ("mapping_bbva_fy2025", ("BBVA", "FY2025"))):
        mf = data[key]
        recs = mf["records"] if isinstance(mf, dict) else mf
        reg = next(x["registro"] for x in
                   data["variant_inventory"]["filings"]
                   if x["issuer"] == issuer_fy[0] and x["fy"] == issuer_fy[1])
        all_rows["extension_mapping"].extend(dtables.mapping_rows(
            ids.filing_id(reg), "es", "en", recs, mf["filing"]))

    # fact plane. The corpus is a true multiset: identical structural
    # keys occur (e.g. SAN-FY2024-es has 4 identical CashAndCashEquivalents
    # facts on context c-3). Occurrence index by deterministic seq order
    # disambiguates fact_id — never dedup, never reorder.
    occ_count: dict[str, int] = {}
    for e in corpus:
        sid, vvid = e["id"], state_vv[e["id"]]
        facts_path = run_dir / f"{sid}.facts.jsonl"
        recs = [json.loads(ln) for ln in
                facts_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
        units_path = run_dir / f"{sid}.units.jsonl"
        units = [json.loads(ln) for ln in
                 units_path.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        if len(units) != len(recs):
            raise SystemExit(f"{sid}: units sidecar count "
                             f"{len(units)} != facts {len(recs)}")
        for seq, rec in enumerate(recs):
            rec["_profile"] = e["kind"]
            base = xfacts.fact_id(canonical_key_of(rec), vvid)
            occ = occ_count.get(base, 0)
            occ_count[base] = occ + 1
            fid = base if occ == 0 else f"{base}#{occ}"
            row, dims = dtables.fact_rows(
                rec, vvid, sid, seq, fid,
                unit_measures=(units[seq]["num"], units[seq]["den"]))
            all_rows["facts"].append(row)
            all_rows["fact_dimension"].extend(dims)

    # provenance
    for e in corpus:
        all_rows["provenance"].append(provenance[e["id"]])

    # deterministic row order per table — the shared write contract
    table_meta = {}
    for tname in dschema.TABLE_ORDER:
        rows = sorted(all_rows[tname], key=parquetio.ROW_ORDER[tname])
        table_meta[tname] = parquetio.write_table(
            tname, rows, ds_dir / f"{tname}.parquet")

    # schema export
    schema_dir = ds_dir / "schema"
    schema_dir.mkdir(exist_ok=True)
    for tname in dschema.TABLE_ORDER:
        write_canonical(dschema.schema_dict(tname),
                        schema_dir / f"{tname}.schema.json")

    inputs = {k: {"path": v["path"], "sha256": v["sha256"]}
              for k, v in load_json(HERE / "g2c_inputs.json").items()}
    inputs["_g2b_pin_file_verified"] = {
        "path": "g2/G2-B-frozen-corpus-rebuild/g2b_inputs.json",
        "note": "all artifact/taxonomy/oracle pins verified byte-exact"}
    man = dmanifest.build_manifest(
        inputs=inputs, tables=table_meta, code_commit=code_commit,
        generator={"tool": "opencnmv.dataset",
                   "python": sys.version.split()[0],
                   "pyarrow": _pkg_version("pyarrow"),
                   "duckdb": _pkg_version("duckdb")},
        params={"compression": "zstd", "row_order": "canonical sorted",
                "serialization": "canonical JSON (LF, indent=1)"},
        limitations=[
            "Parquet files are not committed; they rebuild byte-identically "
            "from the pinned inputs (runA == runB sha256).",
            "extension_mapping UNMATCHED/unpaired records are table-only "
            "(no schema-valid ExtensionMapping form: pair_id required).",
            "IPP filing artifacts attach to filing_version (V1 migration "
            "note); the implicit es variant_version carries artifact_set_id "
            "as content identity.",
            "IPP issuer rows carry nif+lei; frozen ESEF fixtures keep their "
            "original issuer shape (denomination+lei) verbatim.",
        ])
    write_canonical(man, ds_dir / "dataset_manifest.json")
    return {"dataset_dir": str(ds_dir.relative_to(REPO)).replace("\\", "/"),
            "manifest": man}


def _pkg_version(name: str) -> str:
    import importlib.metadata
    return importlib.metadata.version(name)


def build_all(data) -> tuple[dict, dict, dict]:
    """Canonical objects + state->variant_version map + provenance."""
    filings: dict[str, dict] = {}
    state_vv: dict[str, str] = {}
    prov: dict[str, dict] = {}
    inv = data["variant_inventory"]

    # 6 ESEF corpus filings
    for f in inv["filings"]:
        issuer_key, fy = f["issuer"], f["fy"]
        fx = build_esef_filing(data, issuer_key, fy)
        fid = fx["filing_id"]
        extras: dict = {}
        # canonical object's extension_mappings = all paired (schema-valid)
        # records; frozen fixtures keep their fixture-scoped field via the
        # extras overlay.
        mk = f"mapping_{issuer_key.lower()}_{fy.lower()}"
        if mk in data:
            mf = data[mk]
            recs = mf["records"] if isinstance(mf, dict) else mf
            fx["extension_mappings"] = [
                extension_mapping.mapping_record(fid, "es", "en", r)
                for r in recs if r.get("pair_id")]
        # fixture-faithful extras (byte-exact G1-E reconstruction)
        if issuer_key == "BBVA" and fy == "FY2024":
            rec = next(json.loads(ln) for ln in
                       data["bbva_comparison"].decode("utf-8").splitlines()
                       if json.loads(ln).get("class")
                       == "DIVERGENT_SUBMISSION_FACT")
            extras["fact_examples"] = [{
                "note": "I5: same structural key (sans language), "
                        "divergent payload",
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
            extras["extension_mappings"] = []
        if issuer_key == "SAN" and fy == "FY2024":
            counts: dict = {}
            for r in (data[mk]["records"] if isinstance(data[mk], dict)
                      else data[mk]):
                counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
            example = next(r for r in data[mk]["records"]
                           if extension_mapping.rewrites_identity(r))
            extras["extension_mappings"] = [
                extension_mapping.mapping_record(fid, "es", "en", example)]
            extras["extension_mapping_summary"] = counts
        name = f"{issuer_key.lower()}_{fy.lower()}"
        CanonicalFiling.model_validate(fx)
        filings[name] = {"fx": fx, "extras": extras or None,
                         "extra_artifacts": []}
        for lang in ("es", "en"):
            sid = f"{issuer_key}-{fy}-{lang}"
            if any(v["variant_id"] == ids.variant_id(fid, lang)
                   for v in fx["submission_variants"]):
                state_vv[sid] = ids.variant_version_id(
                    ids.variant_id(fid, lang), 1)
                v = f["views"][lang]
                pref = v["preserved_reference"]
                prov[sid] = {
                    "state_id": sid, "filing_id": fid,
                    "variant_version_id": state_vv[sid],
                    "artifact_id": ids.artifact_id(v["package"]["sha256"]),
                    "role": "ESEF_PACKAGE_ZIP_XBRL",
                    "sha256": v["package"]["sha256"],
                    "byte_size": v["package"]["bytes"],
                    "media_type": v["package"]["content_type"],
                    "source_url": None, "resolved_url": None,
                    "retrieved_at": None, "http_status": None,
                    "evidence_path": pref["path"].replace("\\", "/"),
                    "arelle_version": None, "lexical_shim": None}

    # TEF lifecycle fixture (out-of-corpus, frozen in G1-E). Event evidence
    # documents become version_event-owned EVENT_DOCUMENT artifact rows.
    fx_tef = build_tef(data)
    CanonicalFiling.model_validate(fx_tef)
    tef_docs = []
    for ev in fx_tef["version_events"]:
        aid = ev["evidence_artifact_id"]
        doc = next(d for d in data["g1d_tef20484"]["phase2"]["es"]["docs"]
                   if ids.artifact_id(d["sha256"]) == aid)
        tef_docs.append({
            "owner_kind": "version_event", "owner_id": ev["event_id"],
            "artifact_ordinal": 0, "artifact_id": aid,
            "role": "EVENT_DOCUMENT", "sha256": doc["sha256"],
            "bytes": None, "media_type": "application/pdf",
            "source_url": None, "package_lang_tag": None})
    filings["tef_20484"] = {"fx": fx_tef, "extras": None,
                            "extra_artifacts": tef_docs}

    # 15 IPP filings
    for fx, rec, name in build_ipp_filings(data):
        CanonicalFiling.model_validate(fx)
        slot = name[:-4].split("-")           # ipp,SAN,I,semestre,de,2024
        sid = f"{slot[1]}-{'H1' if slot[2] == 'I' else 'H2'}-{slot[5]}"
        filings[f"ipp_{slot[1].lower()}_{sid.split('-',1)[1].lower()}"] = \
            {"fx": fx, "extras": None, "extra_artifacts": []}
        fid = fx["filing_id"]
        state_vv[sid] = ids.variant_version_id(ids.variant_id(fid, "es"), 1)
        prov[sid] = {
            "state_id": sid, "filing_id": fid,
            "variant_version_id": state_vv[sid],
            "artifact_id": ids.artifact_id(rec["sha256"].lower()),
            "role": "IPP_XBRL",
            "sha256": rec["sha256"].lower(),
            "byte_size": rec["byte_size"],
            "media_type": rec["media_type"],
            "source_url": rec["source_url"],
            "resolved_url": rec["final_url"],
            "retrieved_at": rec["retrieved_at"],
            "http_status": rec["http_status"],
            "evidence_path": rec["evidence_path"].replace("\\", "/"),
            "arelle_version": None, "lexical_shim": None}
    return filings, state_vv, prov


def main():
    data = load_inputs()
    pin_bad = verify_g2b_pins()
    print(f"input pins: {len(pin_bad)} mismatches", flush=True)
    if pin_bad:
        raise SystemExit(f"g2b input pin mismatches: {pin_bad}")
    corpus = data["g2b_corpus"]

    code_commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True,
        text=True, cwd=REPO).stdout.strip()

    filings, state_vv, prov = build_all(data)
    print(f"canonical filings: {len(filings)}", flush=True)

    results = {"runs": {}}
    for run_name, hashseed in (("A", 17), ("B", 991)):
        run_dir = OUT / f"run{run_name}"
        run_dir.mkdir(parents=True, exist_ok=True)
        env = isolated_env(run_dir / "_isolate", hashseed)
        for e in corpus:
            print(f"[run{run_name}] {e['id']}", flush=True)
            res = run_parse(e, run_dir, env)
            print("   ", json.dumps(res)[:200], flush=True)
            if res.get("status") != "OK":
                raise SystemExit(f"parse failed: {e['id']}: {res}")
        # fill per-state parse provenance
        for e in corpus:
            s = load_json(run_dir / f"{e['id']}.model_summary.json")
            prov[e["id"]]["arelle_version"] = s["arelle_version"]
            prov[e["id"]]["lexical_shim"] = bool(s["lexical_shim"])
        results["runs"][run_name] = materialize_run(
            run_dir, corpus, data, filings, state_vv, prov, code_commit)
        print(f"[run{run_name}] dataset -> "
              f"{results['runs'][run_name]['dataset_dir']}", flush=True)

    (OUT / "materialize_results.json").write_bytes(json.dumps(
        {"runs": {k: {"dataset_dir": v["dataset_dir"],
                      "corpus_logical_sha256":
                          v["manifest"]["corpus_logical_sha256"],
                      "table_sha256": {t: m["sha256"] for t, m in
                                       v["manifest"]["tables"].items()}}
                  for k, v in results["runs"].items()}},
        indent=1, ensure_ascii=False).encode("utf-8"))
    print("wrote", OUT / "materialize_results.json")


if __name__ == "__main__":
    main()
