# R15 — OFFLINE_REBUILD_DETERMINISTIC (single offline rebuild)
#
# Zero discovery: no CNMV/ESMA/xbrl.org/GLEIF access, no listaifi/ListadoIFA,
# no ?e= fetches. Starts from a CLOSED local input set whose sha256 is verified
# against the frozen manifests BEFORE any processing:
#   - R7 raw corpus artefacts (27)            + artifact_manifest.json
#   - R10 taxonomy packages (official+derived)+ taxonomy_manifest.json
#   - R13 preserved pages (ListadoIFA-r13, infadicionifa-r13) + fetch_manifest
#   - canonicalizer/harness code (this file, r11_parse.py, r12_parse.py)
#   - arelle-release==2.44.0 + fingerprint-gated base64 shim
#
# Defense in depth:
#   (a) preflight UNGUARDED connects to cnmv.es / xbrl.org / esma.europa.eu —
#       expected reachable (proves the host has connectivity, so denial is real);
#   (b) socket deny-all sentinel installed before the rebuild — every connect /
#       create_connection / getaddrinfo raises and is logged;
#   (c) preflight GUARDED connects — MUST raise the sentinel;
#   (d) Arelle internetConnectivity="offline" (inside the R11/R12 harness code);
#   (e) empty isolated Arelle cache via TMP redirect (set by the orchestrator);
#   (f) best-effort file-read audit via builtins.open — reads outside the
#       allowed roots (repo, run root, interpreter/venv, C:\Windows) are flagged.
#       (Covers Python-level open only; C-level readers such as libxml2 are not
#       intercepted — stated honestly in the manifest.)
#
# Modes:
#   full          rebuild all 21 XBRL filings + offline projections
#   starve-esef   SAN-FY2025 only, esef_taxonomy_2024.zip removed -> MUST FAIL
#   starve-ipp-xl SAN-H1-2024 only, xl-2003-12-31.xsd removed from the derived
#                 IPP package -> MUST FAIL (or expose a builtin-cache fallback,
#                 which is itself recorded as evidence)

import argparse, builtins, hashlib, importlib.util, json, os, re, socket, sys, time
from datetime import datetime, timezone
from pathlib import Path

GATE = Path(__file__).resolve().parent
REPO = GATE.parents[1]
R07E = REPO / "g0-r" / "R07-raw-retrieval" / "evidence"
R10E = REPO / "g0-r" / "R10-taxonomy-pinning" / "evidence"
R13E = REPO / "g0-r" / "R13-source-revision-detection" / "evidence"
R13D = REPO / "g0-r" / "R13-source-revision-detection"

CONNECT_PROBE_HOSTS = ["www.cnmv.es", "www.xbrl.org", "www.esma.europa.eu"]

net_attempts = []          # (host, port, phase)
unapproved_reads = []      # paths outside allowed roots


# ---------------------------------------------------------------- net guard
def _install_socket_sentinel():
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def deny_connect(self, address, *a, **k):
        net_attempts.append({"connect": str(address)})
        raise OSError(f"R15-NETWORK-DENIED connect {address}")

    def deny_connect_ex(self, address, *a, **k):
        net_attempts.append({"connect_ex": str(address)})
        raise OSError(f"R15-NETWORK-DENIED connect_ex {address}")

    def deny_create(*a, **k):
        net_attempts.append({"create_connection": str(a)})
        raise OSError(f"R15-NETWORK-DENIED create_connection {a}")

    def deny_gai(*a, **k):
        net_attempts.append({"getaddrinfo": str(a[:2])})
        raise OSError(f"R15-NETWORK-DENIED getaddrinfo {a[:2]}")

    socket.socket.connect = deny_connect
    socket.socket.connect_ex = deny_connect_ex
    socket.create_connection = deny_create
    socket.getaddrinfo = deny_gai
    return real_connect, real_create


def _probe_connectivity():
    """Unguarded TCP reachability — proves the host CAN reach the sources."""
    out = {}
    for h in CONNECT_PROBE_HOSTS:
        try:
            s = socket.create_connection((h, 443), timeout=8)
            s.close()
            out[h] = "REACHABLE"
        except OSError as e:
            out[h] = f"FAIL:{type(e).__name__}"
    return out


def _probe_guarded():
    """Guarded connects — every one MUST raise the sentinel."""
    out = {}
    for h in CONNECT_PROBE_HOSTS:
        try:
            socket.create_connection((h, 443), timeout=5)
            out[h] = "UNEXPECTEDLY_REACHED"   # block failed -> run invalid
        except OSError as e:
            out[h] = ("DENIED" if "R15-NETWORK-DENIED" in str(e)
                      else f"DENIED_OTHER:{e}")
    return out


# ------------------------------------------------------------ file auditing
def _install_read_audit(run_root: Path):
    real_open = builtins.open
    allowed = [str(REPO).lower(), str(run_root).lower(),
               str(Path(sys.prefix)).lower(), str(Path(sys.base_prefix)).lower(),
               "c:\\windows", os.environ.get("TMP", "").lower(),
               os.environ.get("TEMP", "").lower()]

    def audited(file, *a, **k):
        try:
            p = os.fspath(file)
            if isinstance(p, str) and ":" in p:
                lp = p.lower()
                if not any(lp.startswith(ar) for ar in allowed if ar):
                    unapproved_reads.append(p)
        except Exception:
            pass
        return real_open(file, *a, **k)

    builtins.open = audited


# ------------------------------------------------------------------ helpers
def sha256f(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest().upper()


def sha256b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest().upper()


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def tcells(tr):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


def classify(motivo: str) -> str:
    m = motivo.lower()
    if "sustitu" in m: return "SUBSTITUTION"
    if "etiquetado" in m or "fichero" in m: return "FILE_TAGGING_CORRECTION"
    if "requerim" in m: return "CNMV_REQUIREMENT_RESPONSE"
    if "certificad" in m: return "CERTIFICATE"
    return "OTHER"


def parse_infadicionifa(html: str):
    events = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = tcells(tr)
        if len(cells) < 2:
            continue
        tok = re.findall(r"verdocumento/ver\?e=([^\"']+)", tr)
        fecha = next((v for v in cells
                      if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v)), None)
        motivo = max(cells, key=len) if cells else ""
        if fecha and motivo and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", motivo):
            events.append({"fecha": fecha, "motivo": motivo,
                           "doc_token": tok[0] if tok else None})
    return events


def schemarefs_ipp(raw: bytes):
    return sorted(set(x.decode() for x in re.findall(
        rb'schemaRef[^>]*?href="([^"]+)"', raw[:200_000])))


def schemarefs_esef_pkg(pkg_path: Path):
    import zipfile
    refs, tpname = set(), None
    with zipfile.ZipFile(pkg_path) as z:
        for n in z.namelist():
            if n.startswith("reports/") and n.endswith((".xhtml", ".html")):
                refs.update(re.findall(rb'schemaRef[^>]*?href="([^"]+)"',
                                       z.read(n)[:400_000]))
            if n.lower().endswith("taxonomypackage.xml"):
                m = re.search(rb"<tp:name>([^<]+)", z.read(n))
                if m:
                    tpname = m.group(1).decode("utf-8", "replace")
    return sorted(r.decode("utf-8", "replace") for r in refs), tpname


# ------------------------------------------------------------- input verify
def verify_inputs():
    """Closed input set: verify every file's sha256 against frozen manifests."""
    checks = []
    r7 = json.loads((REPO / "g0-r/R07-raw-retrieval/artifact_manifest.json")
                    .read_text(encoding="utf-8-sig"))
    for a in r7:
        p = REPO / a["evidence_path"].replace("\\", "/")
        checks.append({"input": str(p.relative_to(REPO)).replace("\\", "/"),
                       "expected": a["sha256"], "actual": sha256f(p)})
    r10 = json.loads((REPO / "g0-r/R10-taxonomy-pinning/taxonomy_manifest.json")
                     .read_text(encoding="utf-8-sig"))
    for row in r10:
        ep = row.get("evidence_path")
        if not ep:
            continue
        p = REPO / ep.replace("\\", "/")
        if p.exists():
            checks.append({"input": str(p.relative_to(REPO)).replace("\\", "/"),
                           "expected": row["sha256"], "actual": sha256f(p)})
    r13f = json.loads((R13E / "fetch_manifest.json").read_text(encoding="utf-8"))
    for m in r13f:
        p = R13E / m["artifact"]
        if p.exists():
            checks.append({"input": f"g0-r/R13-source-revision-detection/evidence/{m['artifact']}",
                           "expected": m["sha256"], "actual": sha256f(p)})
    for code in ["g0-r/R11-esef-arelle-parse/r11_parse.py",
                 "g0-r/R12-ipp-arelle-parse/r12_parse.py",
                 "g0-r/R15-offline-rebuild-deterministic/r15_rebuild.py"]:
        p = REPO / code
        checks.append({"input": code, "expected": None, "actual": sha256f(p)})
    for c in checks:                       # manifests mix upper/lower hex case
        if c["expected"]:
            c["expected"] = c["expected"].upper()
    bad = [c for c in checks if c["expected"] and c["expected"] != c["actual"]]
    return checks, bad, r7


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--mode", default="full",
                    choices=["full", "starve-esef", "starve-ipp-xl"])
    a = ap.parse_args()
    out_dir = a.root / "out"
    parse_dir = out_dir / "parse"
    parse_dir.mkdir(parents=True, exist_ok=True)

    result = {"mode": a.mode,
              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # (a) unguarded reachability — proves host connectivity exists
    result["preflight_unguarded"] = _probe_connectivity()

    # (b)+(c) install sentinel, guarded probes MUST be denied
    _install_socket_sentinel()
    result["preflight_guarded"] = _probe_guarded()
    guarded_ok = all(v == "DENIED" for v in result["preflight_guarded"].values())
    result["network_block_verified"] = guarded_ok
    net_attempts.clear()          # preflight probes are deliberate, not leakage

    # (f) file-read audit
    _install_read_audit(a.root)

    # closed input set verification (BEFORE any processing)
    checks, bad, r7manifest = verify_inputs()
    result["input_verification"] = {
        "checked": len(checks), "mismatches": len(bad),
        "mismatch_detail": bad[:20]}
    if bad:
        result["verdict"] = "ABORT_INPUT_MISMATCH"
        (out_dir / "r15_run_result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print("ABORT: input hash mismatches:", bad)
        return 2

    # import harnesses (r12 import runs the version/fingerprint-gated shim
    # self-test — fails loudly if Arelle or the upstream regex changed)
    r12 = load_mod("r12_parse", REPO / "g0-r/R12-ipp-arelle-parse/r12_parse.py")
    r11 = load_mod("r11_parse", REPO / "g0-r/R11-esef-arelle-parse/r11_parse.py")
    result["arelle_version"] = getattr(
        __import__("arelle"), "__version__", "2.44.0")
    result["lexical_shim"] = r12.XV_LEXICAL_SHIM

    # artifact manifest from preserved R7 manifest + verified raws
    artifacts = []
    for am in r7manifest:
        name = Path(am["evidence_path"]).name
        m = re.match(r"ipp-([A-Z]+)-(I|II)-semestre-de-(\d{4})", name)
        if m:
            fam, iss = "IPP", m.group(1)
            slot = f"H{1 if m.group(2) == 'I' else 2}-{m.group(3)}"
        else:
            m2 = re.match(r"esef-([A-Z]+)-FY(\d{4})(-package)?", name)
            fam, iss, slot = "ESEF", m2.group(1), f"FY{m2.group(2)}"
        artifacts.append({
            "family": fam, "issuer": iss, "slot": slot,
            "source_registration_no": am["source_registration_no"],
            "artifact_role": am["role"],
            # R7 left final_url empty on ESEF packages; source_url is already
            # the ?e= locator there (no redirect happened)
            "stable_final_url": am.get("final_url") or am["source_url"],
            "raw_sha256": am["sha256"], "byte_size": am["byte_size"],
            "media_type": am["media_type"], "file": name})
    artifacts.sort(key=lambda x: (x["family"], x["issuer"], x["slot"],
                                  x["artifact_role"]))

    # events re-derived OFFLINE from R13 preserved pages
    reg_to_iss_slot = {}
    for iss in ISSUERS_ORDER:
        page = R13E / f"ListadoIFA-{iss}-r13.html"
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>",
                             page.read_text(encoding="utf-8", errors="replace"),
                             re.S):
            cells = tcells(tr)
            if len(cells) >= 8 and re.fullmatch(r"31/12/\d{4}", cells[1] or ""):
                reg_to_iss_slot[cells[0]] = (iss, f"FY{cells[1][-4:]}")
    r13fm = {m["artifact"]: m["source_url"] for m in
             json.loads((R13E / "fetch_manifest.json").read_text(encoding="utf-8"))}
    events = []
    for name, url in r13fm.items():
        mm = re.match(r"infadicionifa-(\d+)-r13\.html", name)
        if not mm:
            continue
        nregaud = mm.group(1)
        nreg = re.search(r"nreg=(\d+)&", url).group(1)
        if nregaud not in reg_to_iss_slot:
            continue
        iss, slot = reg_to_iss_slot[nregaud]
        if slot not in ("FY2024", "FY2025"):
            continue                       # non-corpus rows (incl. 19646 fixture)
        for e in parse_infadicionifa(
                (R13E / name).read_text(encoding="utf-8", errors="replace")):
            cls = classify(e["motivo"])
            events.append({"family": "ESEF", "issuer": iss, "slot": slot,
                           "event_registration_no": nreg,
                           "target_source_registration_no": nregaud,
                           "event_type": cls,
                           "creates_version_transition": cls == "SUBSTITUTION",
                           "event_date": e["fecha"],
                           "doc_locator": e["doc_token"]})
    events.sort(key=lambda e: (e["issuer"], e["slot"], e["event_date"],
                               e["event_type"]))

    # ---- starvation modes -------------------------------------------------
    if a.mode == "starve-esef":
        r11.TAX["FY2025"]["packages"] = [
            p for p in r11.TAX["FY2025"]["packages"]
            if "esef_taxonomy_2024" not in p.name]
        r11.R07, r11.EV = R07E, parse_dir
        try:
            s = r11.run_filing("SAN-FY2025", "esef-SAN-FY2025-package.zip",
                               "FY2025")
        except Exception as ex:          # a raised error IS the expected failure
            s = {"status": "FAIL", "run_ok": False, "exception": repr(ex)}
        result["starvation"] = _starve_outcome(
            s, "esef_taxonomy_2024.zip removed from FY2025 package set")
        result["starvation"]["exception"] = s.get("exception")
        return _finish(result, out_dir, net_attempts, unapproved_reads)

    if a.mode == "starve-ipp-xl":
        import zipfile
        filt = a.root / "cnmv-ipp-pkg-minus-xl.zip"
        with zipfile.ZipFile(r12.IPP_PKG) as zin, \
             zipfile.ZipFile(filt, "w", zipfile.ZIP_DEFLATED) as zout:
            removed = []
            for it in zin.infolist():
                if "xl-2003-12-31" in it.filename:
                    removed.append(it.filename)
                    continue
                zout.writestr(it, zin.read(it.filename))
        r12.IPP_PKG = filt
        r12.R07, r12.EV, r12.TMP = R07E, parse_dir, a.root / "entrypoints"
        r12.TMP.mkdir(exist_ok=True)
        try:
            s = r12.run_filing("SAN-H1-2024", "ipp-SAN-I-semestre-de-2024.zip",
                               "SAN", "H1")
        except Exception as ex:
            s = {"status": "FAIL", "run_ok": False, "exception": repr(ex)}
        res = _starve_outcome(s, f"removed members: {removed}")
        res["exception"] = s.get("exception")
        res["dts_resolution"] = s.get("dts_resolution")
        result["starvation"] = res
        return _finish(result, out_dir, net_attempts, unapproved_reads)

    # ---- full rebuild ------------------------------------------------------
    # taxonomy selection from verified raw bytes
    taxonomy = []
    for art in artifacts:
        p = R07E / art["file"]
        if art["artifact_role"] == "IPP_XBRL":
            refs = schemarefs_ipp(p.read_bytes())
            model = ("ipp_en" if any("/en/" in r for r in refs)
                     else "ipp_ge" if any("/ge/" in r for r in refs) else "?")
            taxonomy.append({"filing": f"{art['issuer']}-{art['slot']}",
                             "schema_refs": refs, "model": model,
                             "taxonomy_packages": [
                                 {"name": r12.IPP_PKG.name,
                                  "sha256": sha256f(r12.IPP_PKG)}]})
        elif art["artifact_role"] == "ESEF_PACKAGE_ZIP_XBRL":
            refs, tpname = schemarefs_esef_pkg(p)
            fam = art["slot"]
            taxonomy.append({"filing": f"{art['issuer']}-{art['slot']}",
                             "schema_refs": refs, "issuer_ext_package": tpname,
                             "disclosure": r11.TAX[fam]["disclosure"],
                             "taxonomy_packages": [
                                 {"name": q.name, "sha256": sha256f(q)}
                                 for q in r11.TAX[fam]["packages"]]})
    taxonomy.sort(key=lambda t: t["filing"])

    r11.R07, r11.EV = R07E, parse_dir
    r12.R07, r12.EV, r12.TMP = R07E, parse_dir, a.root / "entrypoints"
    r12.TMP.mkdir(exist_ok=True)

    facts_index = {}
    for art in artifacts:
        if art["artifact_role"] == "IPP_XBRL":
            fid = f"{art['issuer']}-{art['slot']}"
            sem = "H1" if art["slot"].startswith("H1") else "H2"
            s = r12.run_filing(fid, art["file"], art["issuer"], sem)
        elif art["artifact_role"] == "ESEF_PACKAGE_ZIP_XBRL":
            fid = f"{art['issuer']}-{art['slot']}"
            s = r11.run_filing(fid, art["file"], art["slot"])
        else:
            continue
        c = s.get("counts", {})
        facts_index[fid] = {
            "facts_jsonl_sha256": s.get("outputs", {}).get("facts_jsonl_sha256"),
            "facts": c.get("facts"), "contexts": c.get("contexts"),
            "ioerr": s.get("offline_evidence", {}).get("io_errors"),
            "ctrlA": s.get("control_A", {}).get("fact_multiset_equal")}
        print(f"  parsed {fid}: facts={c.get('facts')} "
              f"ioerr={facts_index[fid]['ioerr']}", flush=True)

    source_state = {"artifacts": artifacts, "events": events}
    for name, obj in [("artifact_manifest", artifacts), ("taxonomy", taxonomy),
                      ("events", events), ("facts_index", facts_index),
                      ("source_state", source_state)]:
        (out_dir / f"{name}.json").write_text(
            json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"rebuild: artifacts={len(artifacts)} events={len(events)} "
          f"parsed={len(facts_index)}")
    return _finish(result, out_dir, net_attempts, unapproved_reads)


ISSUERS_ORDER = ("SAN", "BBVA", "IBE")


def _starve_outcome(summary, note):
    c = summary.get("counts", {})
    logs = summary.get("log_code_counts", {})
    missing = sum(v for k, v in logs.items() if "missing" in k.lower()
                  or "IOerror" in k or "ioerr" in k.lower())
    ioerr = summary.get("offline_evidence", {}).get("io_errors")
    failed = (not summary.get("run_ok")) or (ioerr or 0) > 0 or missing > 0 \
        or summary.get("status") == "FAIL"
    return {"note": note, "expected": "FAIL",
            "run_ok": summary.get("run_ok"), "status": summary.get("status"),
            "io_errors": ioerr, "missing_ref_codes": missing,
            "log_code_counts": logs, "facts_loaded": c.get("facts"),
            "outcome": "FAILED_AS_EXPECTED" if failed else "UNEXPECTEDLY_PASSED"}


def _finish(result, out_dir, attempts, reads):
    result["external_connect_attempts_after_guard"] = [
        x for x in attempts]
    result["unapproved_file_reads"] = sorted(set(reads))[:50]
    result["unapproved_file_reads_count"] = len(set(reads))
    result["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out_dir / "r15_run_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("net_block:", result["network_block_verified"],
          "post-guard attempts:", len(attempts),
          "unapproved_reads:", len(set(reads)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
