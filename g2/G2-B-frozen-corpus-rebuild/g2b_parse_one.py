# G2-B worker: parse ONE frozen filing through the production path
#   src/opencnmv/xbrl/arelle.py  ->  src/opencnmv/canonicalize/facts.py
# Runs as a subprocess under an isolated env (PYTHONHASHSEED, XDG_CONFIG_HOME,
# HOME/USERPROFILE/APPDATA/LOCALAPPDATA, TEMP/TMP all run-local).
#
# Guards installed BEFORE any arelle/opencnmv import:
#   - socket deny-all sentinel (network attempts are COUNTED, not just denied)
#   - meta-path import blocker: no g0-r/ or g1/ gate code may be imported
import json, socket, sys, zipfile, gzip
from collections import Counter
from pathlib import Path

NET_ATTEMPTS = []


def _deny(*a, **k):
    NET_ATTEMPTS.append(repr(a)[:200])
    raise RuntimeError("network access forbidden in offline rebuild")


socket.socket.connect = _deny            # type: ignore[attr-defined]
socket.create_connection = _deny         # type: ignore[attr-defined]
socket.getaddrinfo = _deny               # type: ignore[attr-defined]

GATE_ROOTS = ("g0-r", "g0_r", "g1")
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


class _GateBlocker:
    def find_spec(self, name, path=None, target=None):
        top = name.split(".")[0]
        if top in GATE_ROOTS or name.startswith(("r11", "r12", "g1b", "g1a", "g1c", "g1d", "g1e")):
            raise ImportError(f"gate-code import blocked: {name}")
        return None


sys.meta_path.insert(0, _GateBlocker())

from opencnmv.xbrl import arelle as xarelle  # noqa: E402
from opencnmv.xbrl import taxonomy as xtax   # noqa: E402
from opencnmv.canonicalize import facts as xfacts  # noqa: E402
from opencnmv.provenance import hashes          # noqa: E402


def sha256_file(p: Path) -> str:
    return xarelle.sha256_file(p)


def dts_docs(model):
    seen, stack, out = set(), [model.modelDocument], []
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        out.append(d)
        stack.extend(getattr(d, "referencesDocument", {}).keys())
    return out


def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    fid = spec["id"]
    out_dir = Path(spec["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(exist_ok=True)

    artifact = Path(spec["artifact"])
    kind = spec["kind"]
    tax = xtax.esef_taxonomy_set(spec["fy"], Path(spec["tax_dir"])) \
        if kind == "esef" else xtax.ipp_taxonomy_set(Path(spec["tax_dir"]))
    if "override_packages" in spec:
        tax["packages"] = [str(Path(p)) for p in spec["override_packages"]]

    if kind == "ipp":
        entry = xarelle.prepare_xbrl_entrypoint(artifact, work, fid)
    else:
        entry = artifact

    oim_path = out_dir / f"{fid}.oim.json"
    ps = xarelle.ParseSpec(
        entrypoint=str(entry),
        taxonomy_packages=tax["packages"],
        disclosure_system=tax["disclosure"],
        plugins=("validate/ESEF|saveLoadableOIM" if kind == "esef"
                 else "saveLoadableOIM"),
        validate=True,
        oim_path=str(oim_path),
        lexical_shim=(kind == "ipp"),
    )

    with xarelle.ParseSession(ps) as sess:
        m = sess.model
        log_msgs = sess.log_msgs
        (out_dir / f"{fid}.arelle-log.json").write_bytes(
            json.dumps(log_msgs, indent=1, ensure_ascii=False).encode("utf-8"))

        summary = {"filing": fid, "kind": kind, "run_ok": sess.run_ok,
                   "artifact": spec["artifact"],
                   "artifact_sha256": sha256_file(artifact),
                   "arelle_version": xarelle.ARELLE_VERSION,
                   "lexical_shim": getattr(sess, "shim_info", None)}
        if m is None:
            summary["status"] = "FAIL"
            summary["reason"] = "no model loaded"
            (out_dir / f"{fid}.model_summary.json").write_bytes(
                json.dumps(summary, indent=1, ensure_ascii=False).encode("utf-8"))
            print(json.dumps(summary))
            return

        ext_ns = (xtax.extension_namespaces(artifact) if kind == "esef" else set())
        records = xfacts.facts_to_records(
            m, profile=kind, ext_ns=(ext_ns if kind == "esef" else None))
        facts_path = out_dir / f"{fid}.facts.jsonl"
        facts_path.write_bytes(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                    for r in records).encode("utf-8"))

        docs = dts_docs(m)
        dts_detail = []
        for d in docs:
            fp = str(getattr(d, "filepath", "") or "")
            if "opencnmv-pkg.zip" in fp or "esef_taxonomy" in fp:
                src_kind = "taxonomy_package"
            elif "cache" in fp.lower():
                src_kind = "arelle_cache"
            else:
                src_kind = "local_input"
            dts_detail.append({"uri": getattr(d, "uri", ""),
                               "resolved_from": src_kind})
        dts_detail.sort(key=lambda r: r["uri"])

        ioerrors = sum(1 for lm in log_msgs
                       if "Could not load" in str(lm.get("message", ""))
                       or "IOerror" in str(lm.get("code", "")))
        typed_dims = sum(1 for c in m.contexts.values()
                         for d in c.qnameDims.values() if getattr(d, "isTyped", False))
        explicit_dims = sum(1 for c in m.contexts.values()
                            for d in c.qnameDims.values()
                            if getattr(d, "isExplicit", False))

        summary.update({
            "status": "OK",
            "counts": {
                "facts": len(records),
                "contexts": len(m.contexts),
                "units": len(m.units),
                "concepts": len(m.qnameConcepts),
                "dts_documents": len(docs),
                "nil_facts": sum(1 for r in records if r["isNil"]),
                "contexts_explicit_dims": explicit_dims,
                "contexts_typed_dims": typed_dims,
                "fact_languages": sorted({r["lang"] for r in records if r["lang"]}),
            },
            "dts_resolution": dts_detail,
            "offline_evidence": {"io_errors": ioerrors},
            "network_attempts": len(NET_ATTEMPTS),
            "outputs": {"facts_jsonl": facts_path.name,
                        "facts_jsonl_sha256": sha256_file(facts_path)},
        })

        if oim_path.exists():
            oim = json.loads(oim_path.read_text(encoding="utf-8"))
            nsmap = oim.get("documentInfo", {}).get("namespaces", {})
            api_keys = Counter(xfacts.api_key_for_oim(r) for r in records)
            oim_facts = oim.get("facts", {})
            oim_keys = Counter(xfacts.oim_fact_key(fo, nsmap)
                               for fo in oim_facts.values())
            summary["control_A"] = {
                "fact_count_api": len(records),
                "fact_count_oim": len(oim_facts),
                "fact_multiset_equal": api_keys == oim_keys,
                "decimals_distribution_equal":
                    Counter(str(r["decimals"]) for r in records) ==
                    Counter(str(fo.get("decimals")) for fo in oim_facts.values()),
                "nil_count_api": summary["counts"]["nil_facts"],
                "nil_count_oim": sum(1 for fo in oim_facts.values()
                                     if fo.get("value") is None),
            }
            gz_path = out_dir / f"{fid}.oim.json.gz"
            with open(oim_path, "rb") as fi, \
                    gzip.GzipFile(gz_path, "wb", mtime=0) as go:
                go.write(fi.read())
            oim_path.unlink()
            summary["outputs"]["oim_json_gz_sha256"] = sha256_file(gz_path)
        else:
            summary["control_A"] = {"error": "OIM export file not produced"}

        (out_dir / f"{fid}.model_summary.json").write_bytes(
            json.dumps(summary, indent=1, ensure_ascii=False).encode("utf-8"))
        print(json.dumps({"filing": fid, "status": summary["status"],
                          "facts": summary["counts"]["facts"],
                          "ioerr": ioerrors,
                          "ctrlA": summary["control_A"].get("fact_multiset_equal"),
                          "net": len(NET_ATTEMPTS)}))
        if kind == "ipp":
            entry.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
