# G2-C worker: parse ONE frozen filing through the production path
#   src/opencnmv/xbrl/arelle.py  ->  src/opencnmv/canonicalize/facts.py
# Same isolation contract as G2-B (isolated env per run, socket deny-all,
# meta-path blocker against g0-r//g1/ imports). No OIM export — G2-B
# already proved API==OIM; the fact records are the materialization input.
import json
import socket
import sys
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


def sha256_file(p: Path) -> str:
    return xarelle.sha256_file(p)


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

    if kind == "ipp":
        entry = xarelle.prepare_xbrl_entrypoint(artifact, work, fid)
    else:
        entry = artifact

    ps = xarelle.ParseSpec(
        entrypoint=str(entry),
        taxonomy_packages=tax["packages"],
        disclosure_system=tax["disclosure"],
        plugins=("validate/ESEF|saveLoadableOIM" if kind == "esef"
                 else "saveLoadableOIM"),
        validate=True,
        lexical_shim=(kind == "ipp"),
    )

    with xarelle.ParseSession(ps) as sess:
        m = sess.model
        log_msgs = sess.log_msgs
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
        pairs = [(xfacts.fact_record(f, profile=kind,
                                   ext_ns=(ext_ns if kind == "esef" else None)),
                  f.unit) for f in m.facts]
        pairs.sort(key=lambda p: xfacts.fact_sort_key(p[0]))
        records = [p[0] for p in pairs]
        facts_path = out_dir / f"{fid}.facts.jsonl"
        facts_path.write_bytes(
            "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                    for r in records).encode("utf-8"))
        # unit sidecar: the record's unit signature is lossy for splitting
        # (QNames contain "/"); real numerator/denominator measures come
        # from the live model, aligned by seq with facts.jsonl.
        units_path = out_dir / f"{fid}.units.jsonl"
        units_path.write_bytes("".join(
            json.dumps(
                {"num": sorted(xfacts.qn(q) for q in u.measures[0]),
                 "den": sorted(xfacts.qn(q) for q in u.measures[1])}
                if u is not None else {"num": [], "den": []},
                ensure_ascii=False, sort_keys=True) + "\n"
            for _r, u in pairs).encode("utf-8"))

        ioerrors = sum(1 for lm in log_msgs
                       if "Could not load" in str(lm.get("message", ""))
                       or "IOerror" in str(lm.get("code", "")))
        summary.update({
            "status": "OK",
            "counts": {
                "facts": len(records),
                "contexts": len(m.contexts),
                "units": len(m.units),
                "facts_typed_dims": sum(
                    1 for r in records
                    for v in (r.get("dimensions") or {}).values()
                    if v.startswith("T:")),
                "facts_compound_units": sum(
                    1 for r in records if "/" in (r.get("unit") or "")),
                "nil_facts": sum(1 for r in records if r["isNil"]),
            },
            "offline_evidence": {"io_errors": ioerrors},
            "network_attempts": len(NET_ATTEMPTS),
            "outputs": {"facts_jsonl": facts_path.name,
                        "facts_jsonl_sha256": sha256_file(facts_path)},
        })
        (out_dir / f"{fid}.model_summary.json").write_bytes(
            json.dumps(summary, indent=1, ensure_ascii=False).encode("utf-8"))
        print(json.dumps({"filing": fid, "status": summary["status"],
                          "facts": summary["counts"]["facts"],
                          "ioerr": ioerrors, "net": len(NET_ATTEMPTS)}))
        if kind == "ipp":
            entry.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
