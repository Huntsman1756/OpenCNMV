# R14 — ONLINE_CAPTURE_DETERMINISTIC (single capture run)
#
# One isolated online capture: discovery (listaifi/ListadoIFA) -> raw artefact
# retrieval (27: 15 IPP_XBRL + 6 ESEF_COVER + 6 ESEF_PACKAGE_ZIP_XBRL) ->
# infadicionifa event walk -> taxonomy selection -> offline Arelle parse via the
# SAME harness code as R11/R12 (imported, globals redirected to this run's
# root). Emits canonical projections + a volatile fetch_log + a control
# projection (includes retrieved_at and the ephemeral ?t={GUID}) for the
# comparator's negative test.
#
# Usage: python r14_capture.py --root <run_root>   (PYTHONHASHSEED/TMP set by
# the orchestrator; TMP isolation also gives Arelle an empty per-run cache on
# Windows: tempfile.gettempdir() -> <root>\local\temp -> <root>\local\Arelle)

import argparse, hashlib, importlib.util, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path

import requests

GATE = Path(__file__).resolve().parent
REPO = GATE.parents[1]
R07 = REPO / "g0-r" / "R07-raw-retrieval" / "evidence"

BASE = "https://www.cnmv.es"
LISTAIFI = BASE + "/portal/consultas/ifi/listaifi?lang=es&nif={nif}"
DETALLE = BASE + "/portal/aldia/detalleifialdia.aspx?nreg={nreg}"
DL_IPP = BASE + "/portal/consultas/wuc/descargaxbrlipp.ashx?t=%7b{guid}%7d"
LISTADO = BASE + "/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif={nif}"
INFAD = BASE + "/Portal/consultas/ifa/infadicionifa.aspx?id=0&lang=es&nreg={nreg}&nregaud={nregaud}"
VER = BASE + "/webservices/verdocumento/ver?e={tok}"

ISSUERS = {"SAN": "A39000013", "BBVA": "A48265169", "IBE": "A-48010615"}
IPP_SLOTS = [("I", 2024), ("II", 2024), ("I", 2025), ("II", 2025), ("I", 2026)]
ESEF_SLOTS = [2024, 2025]
UA = {"User-Agent": "OpenCNMV G0-R evidence probe (research; contact via repo)"}

fetch_log = []
sess = requests.Session()
sess.headers.update(UA)


def sha256b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest().upper()


def sha256f(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest().upper()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def get(url: str, note: str):
    t0 = time.time()
    r = sess.get(url, timeout=180)
    body = r.content
    fetch_log.append({
        "note": note, "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "http_status": r.status_code, "media_type": r.headers.get("Content-Type"),
        "byte_size": len(body), "sha256": sha256b(body),
        "final_url": r.url, "elapsed_ms": int((time.time() - t0) * 1000),
        "http_date": r.headers.get("Date"),
    })
    return r, body


def tcells(tr: str):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]


def parse_listaifi(html: str):
    """slot label -> nreg from the IPP listing."""
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        m = re.search(r"(?i)(II|I)\s+semestre\s+de\s+(\d{4})", tr)
        n = re.search(r"nreg=(\d+)", tr)
        if m and n:
            out[(m.group(1).upper(), int(m.group(2)))] = n.group(1)
    return out


def parse_listado_rows(html: str):
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = tcells(tr)
        if len(cells) < 8:
            continue
        toks = re.findall(r"ver\?e=([A-Za-z0-9%+/\-]+)", tr)
        link = re.findall(r"nreg=(\d+)&(?:amp;)?nregaud=(\d+)", tr)
        m = re.match(r"31/12/(\d{4})$", cells[1])
        if m and toks:
            yield {"registro": cells[0], "year": int(m.group(1)),
                   "fecha_publicacion": cells[2], "tokens": toks,
                   "ampliacion": bool(cells[7]),
                   "ampl_link": link[0] if link else None}


def parse_infadicionifa(html: str):
    events = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = tcells(tr)
        if len(cells) < 2:
            continue
        tok = re.findall(r"verdocumento/ver\?e=([^\"']+)", tr)
        fecha = next((v for v in cells if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v)), None)
        motivo = max(cells, key=len) if cells else ""
        if fecha and motivo and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", motivo):
            events.append({"fecha": fecha, "motivo": motivo,
                           "doc_token": tok[0] if tok else None})
    return events


def classify(motivo: str) -> str:
    m = motivo.lower()
    if "sustitu" in m: return "SUBSTITUTION"
    if "etiquetado" in m or "fichero" in m: return "FILE_TAGGING_CORRECTION"
    if "requerim" in m: return "CNMV_REQUIREMENT_RESPONSE"
    if "certificad" in m: return "CERTIFICATE"
    return "OTHER"


def schemarefs_ipp(raw: bytes):
    return sorted(set(re.findall(
        rb'schemaRef[^>]*?href="([^"]+)"', raw[:200_000])))


def schemarefs_esef_pkg(pkg_path: Path):
    """schemaRefs from the package's reports/*.xhtml + taxonomy package name."""
    import zipfile
    refs, tpname = set(), None
    with zipfile.ZipFile(pkg_path) as z:
        for n in z.namelist():
            if n.startswith("reports/") and n.endswith((".xhtml", ".html")):
                head = z.read(n)[:400_000]
                refs.update(re.findall(rb'schemaRef[^>]*?href="([^"]+)"', head))
            if n.lower().endswith("taxonomypackage.xml"):
                m = re.search(rb"<tp:name>([^<]+)", z.read(n))
                if m:
                    tpname = m.group(1).decode("utf-8", "replace")
    return sorted(r.decode("utf-8", "replace") for r in refs), tpname


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--run", default="run")
    a = ap.parse_args()
    raw_dir = a.root / "raw"; parse_dir = a.root / "out" / "parse"
    out_dir = a.root / "out"
    for d in (raw_dir, parse_dir):
        d.mkdir(parents=True, exist_ok=True)

    discovery, artifacts, events, volatile = [], [], [], []
    source_state = []

    for iss, nif in ISSUERS.items():
        # ---------- IPP discovery ----------
        _, body = get(LISTAIFI.format(nif=nif), f"listaifi-{iss}")
        nregs = parse_listaifi(body.decode("utf-8", errors="replace"))
        for sem, yr in IPP_SLOTS:
            slot = f"H{1 if sem == 'I' else 2}-{yr}"
            nreg = nregs.get((sem, yr))
            rec = {"family": "IPP", "issuer": iss, "slot": slot,
                   "source_registration_no": nreg}
            discovery.append(rec)
            if not nreg:
                rec["error"] = "NREG_NOT_FOUND"
                continue
            _, det = get(DETALLE.format(nreg=nreg), f"detalle-{iss}-{slot}")
            g = re.search(rb"descargaxbrlipp\.ashx\?t=\{([0-9a-f-]{36})\}", det)
            if not g:
                rec["error"] = "GUID_NOT_FOUND"
                continue
            guid = g.group(1).decode()
            r, body = get(DL_IPP.format(guid=guid), f"ipp-{iss}-{slot}")
            name = f"ipp-{iss}-{sem}-semestre-de-{yr}.zip"
            (raw_dir / name).write_bytes(body)
            art = {"family": "IPP", "issuer": iss, "slot": slot,
                   "source_registration_no": nreg, "artifact_role": "IPP_XBRL",
                   "stable_final_url": r.url, "raw_sha256": sha256b(body),
                   "byte_size": len(body),
                   "media_type": fetch_log[-1]["media_type"],
                   "file": name}
            artifacts.append(art)
            volatile.append({"artifact": name, "t_guid": guid,
                             "retrieved_at": fetch_log[-1]["retrieved_at"]})

        # ---------- ESEF discovery ----------
        _, body = get(LISTADO.format(nif=nif), f"ListadoIFA-{iss}")
        for row in parse_listado_rows(body.decode("utf-8", errors="replace")):
            if row["year"] not in ESEF_SLOTS:
                continue
            slot = f"FY{row['year']}"
            toks = row["tokens"]
            rec = {"family": "ESEF", "issuer": iss, "slot": slot,
                   "source_registration_no": row["registro"],
                   "component_locators": {
                       "ESEF_COVER": toks[0],
                       "IXBRL_CONSOLIDATED": toks[1] if len(toks) > 1 else None,
                       "ESEF_PACKAGE_ZIP_XBRL": toks[2] if len(toks) > 2 else None},
                   "ampliacion": row["ampliacion"]}
            discovery.append(rec)
            for role, tok, fname in (
                    ("ESEF_COVER", toks[0], f"esef-{iss}-{slot}.zip"),
                    ("ESEF_PACKAGE_ZIP_XBRL", toks[2] if len(toks) > 2 else None,
                     f"esef-{iss}-{slot}-package.zip")):
                if not tok:
                    continue
                r, body = get(VER.format(tok=tok), fname[:-4])
                (raw_dir / fname).write_bytes(body)
                artifacts.append({"family": "ESEF", "issuer": iss, "slot": slot,
                                  "source_registration_no": row["registro"],
                                  "artifact_role": role,
                                  "stable_final_url": r.url,
                                  "raw_sha256": sha256b(body),
                                  "byte_size": len(body),
                                  "media_type": fetch_log[-1]["media_type"],
                                  "file": fname})
                volatile.append({"artifact": fname,
                                 "retrieved_at": fetch_log[-1]["retrieved_at"]})
            # ---------- events (complementary info) ----------
            if row["ampliacion"] and row["ampl_link"]:
                nreg, nregaud = row["ampl_link"]
                _, pg = get(INFAD.format(nreg=nreg, nregaud=nregaud),
                            f"infadicionifa-{nregaud}")
                for e in parse_infadicionifa(pg.decode("utf-8", errors="replace")):
                    events.append({
                        "family": "ESEF", "issuer": iss, "slot": slot,
                        "event_registration_no": nreg,
                        "target_source_registration_no": nregaud,
                        "event_type": classify(e["motivo"]),
                        "creates_version_transition":
                            classify(e["motivo"]) == "SUBSTITUTION",
                        "event_date": e["fecha"],
                        "doc_locator": e["doc_token"],
                    })

    # ---------- taxonomy selection (from raw bytes, pre-Arelle) ----------
    import importlib.util as iu

    def load_mod(name, path):
        spec = iu.spec_from_file_location(name, path)
        mod = iu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    r12 = load_mod("r12_parse", REPO / "g0-r/R12-ipp-arelle-parse/r12_parse.py")
    r11 = load_mod("r11_parse", REPO / "g0-r/R11-esef-arelle-parse/r11_parse.py")

    taxonomy = []
    for art in artifacts:
        if art["artifact_role"] not in ("IPP_XBRL", "ESEF_PACKAGE_ZIP_XBRL"):
            continue
        p = raw_dir / art["file"]
        if art["artifact_role"] == "IPP_XBRL":
            refs = [x.decode() for x in schemarefs_ipp(p.read_bytes())]
            model = ("ipp_en" if any("/en/" in r for r in refs)
                     else "ipp_ge" if any("/ge/" in r for r in refs) else "?")
            pkgs = [{"name": r12.IPP_PKG.name, "sha256": sha256f(r12.IPP_PKG)}]
            taxonomy.append({"filing": f"{art['issuer']}-{art['slot']}",
                             "schema_refs": refs, "model": model,
                             "taxonomy_packages": pkgs})
        else:
            refs, tpname = schemarefs_esef_pkg(p)
            fam = "FY2025" if "2025" in art["slot"] else "FY2024"
            pkgs = [{"name": q.name, "sha256": sha256f(q)}
                    for q in r11.TAX[fam]["packages"]]
            taxonomy.append({"filing": f"{art['issuer']}-{art['slot']}",
                             "schema_refs": refs, "issuer_ext_package": tpname,
                             "disclosure": r11.TAX[fam]["disclosure"],
                             "taxonomy_packages": pkgs})
    taxonomy.sort(key=lambda t: t["filing"])

    # ---------- offline parse via R11/R12 harness code ----------
    r11.R07 = raw_dir
    r11.EV = parse_dir
    r12.R07 = raw_dir
    r12.EV = parse_dir
    r12.TMP = a.root / "entrypoints"
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
            "ctrlA": s.get("control_A", {}).get("fact_multiset_equal"),
        }
        print(f"  parsed {fid}: facts={c.get('facts')} ioerr={facts_index[fid]['ioerr']}",
              flush=True)

    discovery.sort(key=lambda d: (d["family"], d["issuer"], d["slot"]))
    artifacts.sort(key=lambda x: (x["family"], x["issuer"], x["slot"],
                                  x["artifact_role"]))
    events.sort(key=lambda e: (e["issuer"], e["slot"], e["event_date"],
                               e["event_type"]))
    source_state = {"artifacts": artifacts, "events": events}
    control = {"artifacts": artifacts,
               "volatile": volatile}   # negative control (MUST differ A vs B)

    for name, obj in [("discovery", discovery), ("artifact_manifest", artifacts),
                      ("taxonomy", taxonomy), ("events", events),
                      ("facts_index", facts_index),
                      ("source_state", source_state),
                      ("control_projection", control),
                      ("fetch_log", fetch_log)]:
        (out_dir / f"{name}.json").write_text(
            json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{a.run}: artifacts={len(artifacts)} events={len(events)} "
          f"parsed={len(facts_index)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
