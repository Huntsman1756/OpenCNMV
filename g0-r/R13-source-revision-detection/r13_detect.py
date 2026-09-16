"""R13 — SOURCE_REVISION_DETECTION.

Probes the CNMV source for revision/substitution semantics:

  13A REVISION_EXISTS            — walk "Ampliación información" (col 8 of
                                   ListadoIFA) for every corpus row + the
                                   IBE-FY2022 fixture; classify each event.
  13B REVISION_TARGET_EXACT      — prove the source binds a revision event to
                                   the exact target filing via `nregaud`
                                   (= Nº Registro Oficial), not via inference.
  13C REVISION_SEMANTICS_EXTRACTED — extract the in-document correction
                                   semantics from the IBE H1-2009 IPP
                                   "Explicación de las principales
                                   modificaciones" fixture, and fetch the
                                   IBE-FY2022 substitution certificate docs.

Evidence discipline (AGENTS.md §9): raw bytes preserved unmodified, every
artefact hashed (sha256), source_url/retrieved_at/http metadata recorded in
fetch_manifest.json. Nothing here mutates raw artefacts fetched by R7.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
EV = ROOT / "evidence"
R1 = ROOT.parent / "R01-discovery" / "evidence"

BASE_IFA = "https://www.cnmv.es/Portal/consultas/ifa"
LISTADO = f"{BASE_IFA}/listadoifa?id=0&lang=es&nif={{nif}}"
INFAD = f"{BASE_IFA}/infadicionifa.aspx?id=0&lang=es&nreg={{nreg}}&nregaud={{nregaud}}"
VER = "https://www.cnmv.es/webservices/verdocumento/ver?e={tok}"

ISSUERS = {
    "SAN": "A39000013",
    "BBVA": "A48265169",
    "IBE": "A-48010615",
}

# IBE FY2022 falsification fixture (outside the frozen corpus): registro
# oficial 19646 carries a documented substitution certificate (28/02/2023).
FIXTURE_NREGAUD = "19646"

# IBE H1-2009 IPP (pre-XBRL PDF) containing "Explicación de las principales
# modificaciones" with a Corregida / Previamente presentada / Diferencia table.
H1_2009_TOK = "P8P4sdwbT5isEKmQC7DawbhYkc6XIBZ7%2BYWKJxFMOZT1xVx9TYwe6nqlQTLZolJy"

UA = {"User-Agent": "OpenCNMV G0-R evidence probe (research; contact via repo)"}
_manifest = []


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fetch(url: str, name: str) -> bytes:
    r = requests.get(url, headers=UA, timeout=90)
    body = r.content
    (EV / name).write_bytes(body)
    _manifest.append({
        "artifact": name,
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "http_status": r.status_code,
        "media_type": r.headers.get("Content-Type"),
        "byte_size": len(body),
        "sha256": sha256(body),
    })
    return body


def txt(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def parse_listado(html: str):
    """Yield per row: registro, fecha_ef, fecha_pub, ampliacion, nreg, nregaud."""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) < 8:
            continue
        vals = [txt(c).strip() for c in cells]
        link = re.findall(r"nreg=(\d+)&(?:amp;)?nregaud=(\d+)", tr)
        yield {
            "registro_oficial": vals[0],
            "fecha_estados": vals[1],
            "fecha_publicacion": vals[2],
            "ampliacion": vals[7],
            "nreg": link[0][0] if link else None,
            "nregaud": link[0][1] if link else None,
        }


def parse_infadicionifa(html: str):
    """Extract (fecha, motivo, doc token) triples from an infadicionifa page."""
    events = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) < 2:
            continue
        vals = [txt(c).strip() for c in cells]
        tok = re.findall(r"verdocumento/ver\?e=([^\"']+)", tr)
        fecha = next((v for v in vals if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v)), None)
        motivo = max(vals, key=len) if vals else ""
        if fecha and motivo and not re.fullmatch(r"\d{2}/\d{2}/\d{4}", motivo):
            events.append({"fecha": fecha, "motivo": motivo,
                           "doc_token": tok[0] if tok else None})
    # header context: which filing this page describes
    hdr = txt(html)
    m = re.search(r"Nº?\s*Registro[^\d]*(\d{4,})", hdr)
    # issuer appears in <title>: "... a requerimiento de la CNMV - IBERDROLA, S.A."
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
    issuer = title.group(1).rsplit("-", 1)[-1].strip() if title else None
    return events, {
        "registro_in_header": m.group(1) if m else None,
        "issuer_in_header": issuer,
    }


def classify(motivo: str) -> str:
    m = motivo.lower()
    if "sustitu" in m:
        return "SUBSTITUTION"
    if "etiquetado" in m or "fichero" in m:
        return "FILE_TAGGING_CORRECTION"
    if "requerim" in m:
        return "CNMV_REQUIREMENT_RESPONSE"
    if "certificad" in m:
        return "CERTIFICATE"
    return "OTHER"


def main() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    out = {"gate": "R13", "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    # ---- 13A: re-fetch the listings, diff vs R1 snapshot, walk 'Sí' rows ----
    listings, drift = {}, []
    for iss, nif in ISSUERS.items():
        body = fetch(LISTADO.format(nif=nif.lower()), f"ListadoIFA-{iss}-r13.html")
        snap = (R1 / f"ListadoIFA-{iss}.html").read_bytes()
        listings[iss] = list(parse_listado(body.decode("utf-8", errors="replace")))
        snap_rows = list(parse_listado(
            snap.decode("utf-8", errors="replace")))
        snap_amp = {r["registro_oficial"] for r in snap_rows if r["ampliacion"]}
        now_amp = {r["registro_oficial"] for r in listings[iss] if r["ampliacion"]}
        drift.append({"issuer": iss,
                      "r1_snapshot_sha256": sha256(snap),
                      "r13_fetch_sha256": sha256(body),
                      "identical_bytes": sha256(snap) == sha256(body),
                      "r1_ampliacion_registros": sorted(snap_amp),
                      "r13_ampliacion_registros": sorted(now_amp),
                      "ampliacion_set_identical": snap_amp == now_amp,
                      "registros_added_since_r1": sorted(
                          {r["registro_oficial"] for r in listings[iss]}
                          - {r["registro_oficial"] for r in snap_rows})})
        rows = listings[iss]
        print(f"{iss}: {len(rows)} rows, "
              f"{sum(1 for r in rows if r['ampliacion'])} with Sí, "
              f"drift={'NO' if drift[-1]['identical_bytes'] else 'YES'}")

    corpus_rows = [r for iss in listings for r in listings[iss]
                   if r["fecha_estados"].endswith(("/2024", "/2025"))]
    targets = {r["nregaud"]: (r["nreg"], r["registro_oficial"]) for r in corpus_rows}
    targets[FIXTURE_NREGAUD] = (None, FIXTURE_NREGAUD)  # nreg resolved from R1 link

    # nreg for the fixture comes from the R1 IBE listing snapshot
    for r in list(parse_listado((R1 / "ListadoIFA-IBE.html").read_text(
            encoding="utf-8", errors="replace"))):
        if r["nregaud"] == FIXTURE_NREGAUD:
            targets[FIXTURE_NREGAUD] = (r["nreg"], FIXTURE_NREGAUD)

    events, target_check = [], []
    for nregaud, (nreg, registro) in sorted(targets.items()):
        body = fetch(INFAD.format(nreg=nreg, nregaud=nregaud),
                     f"infadicionifa-{nregaud}-r13.html")
        evs, hdr = parse_infadicionifa(body.decode("utf-8", errors="replace"))
        # ---- 13B: the URL's nregaud must equal the registro oficial shown ----
        target_check.append({
            "nregaud_param": nregaud,
            "registro_in_page": hdr["registro_in_header"],
            "registro_in_row": registro,
            "exact_binding": hdr["registro_in_header"] == nregaud == registro,
            "issuer_in_page": hdr["issuer_in_header"],
        })
        for e in evs:
            e["target_nregaud"] = nregaud
            e["class"] = classify(e["motivo"])
            e["corpus"] = nregaud != FIXTURE_NREGAUD
            events.append(e)
            print(f"  nregaud={nregaud} {e['fecha']} [{e['class']}] {e['motivo'][:90]}")

    # ---- 13C: fetch revision-semantics documents ----
    # (a) IBE-FY2022 substitution + formulation certificates
    subs = [e for e in events if e["target_nregaud"] == FIXTURE_NREGAUD and e["doc_token"]]
    for i, e in enumerate(subs):
        body = fetch(VER.format(tok=e["doc_token"]), f"ibe-fy2022-cert{i+1}.pdf")
        e["doc_sha256"] = sha256(body)
        e["doc_media_type"] = _manifest[-1]["media_type"]

    # (b) IBE H1-2009 IPP in-document correction table
    body = fetch(VER.format(tok=H1_2009_TOK), "ibe-h1-2009-ipp.pdf")
    semantics = {"artifact": "ibe-h1-2009-ipp.pdf", "sha256": sha256(body)}
    try:
        import io
        import pypdf
        full = "\n".join((p.extract_text() or "")
                         for p in pypdf.PdfReader(io.BytesIO(body)).pages)
        (EV / "ibe-h1-2009-ipp.txt").write_text(full, encoding="utf-8")
        i = full.find("modificaciones respecto")
        excerpt = full[i:i + 3200] if i >= 0 else full[:2000]
        semantics.update({
            "section": "II. INFORMACIÓN COMPLEMENTARIA A LA INFORMACIÓN "
                       "PERIÓDICA PREVIAMENTE PUBLICADA",
            "excerpt_sha256": sha256(excerpt.encode("utf-8")),
            "has_correction_table": "Corregida" in full and "Diferencia" in full,
            "excerpt_preview": excerpt[:1200],
        })
        # deterministic amount extraction from the corrections table
        rows = re.findall(
            r"(Activos por impuestos corrientes|Pasivos por impuestos corrientes)"
            r"\s+([\d\.]+)\s+([\d\.]+)\s+(-?[\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+(-?[\d\.]+)",
            full)
        semantics["corrections"] = [
            {"concept": c, "consolidated": {"corregida": a, "previa": b, "dif": d},
             "individual": {"corregida": e_, "previa": f, "dif": g}}
            for c, a, b, d, e_, f, g in rows]
    except Exception as ex:  # pragma: no cover
        semantics["extraction_error"] = repr(ex)

    out.update({
        "drift_vs_r1_snapshot": drift,
        "events": events,
        "target_exact_checks": target_check,
        "h1_2009_semantics": semantics,
        "counts": {
            "corpus_rows_checked": len(corpus_rows),
            "corpus_rows_with_ampliacion": sum(1 for r in corpus_rows if r["ampliacion"]),
            "events_total": len(events),
            "by_class": {c: sum(1 for e in events if e["class"] == c)
                         for c in sorted({e["class"] for e in events})},
        },
    })
    (EV / "r13_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    (EV / "fetch_manifest.json").write_text(
        json.dumps(_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out["counts"], indent=2, ensure_ascii=False))
    print("target_exact all bound:",
          all(c["exact_binding"] for c in target_check))


if __name__ == "__main__":
    main()
