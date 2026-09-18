"""G3-A freeze leg — sample construction before any filing capture.

Implements the freeze protocol preregistered in README.md:

  1. universe POST  busqueda?id=25 (empty denomination, wide window)
  2. unfiltered listaifi (supplementary)
  3. datosgenerales ficha per universe nif  (identity/sector/LEI/capital)
  4. deterministic stratified selection      -> sample.json
  5. per-sampled-issuer listing (listaifi + ListadoIFA + <=3 infadicion
     docs)                                    -> expected_inventory.json

Every response is preserved byte-for-byte under _out/freeze/ (write-once
content-addressed) and logged in the run manifest fetch_log.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))

from opencnmv.capture.fetch import (EvidenceStore, PoliteSession,  # noqa: E402
                                    new_manifest, utcnow)

OUT = HERE / "_out"
FREEZE = OUT / "freeze"
MIN_DELAY = 2.5

BASE = "https://www.cnmv.es"
SEARCH_URL = BASE + "/portal/consultas/busqueda?id=25&lang=es"
LISTAIFI = BASE + "/portal/consultas/ifi/listaifi?lang=es"
LISTAIFI_NIF = (BASE + "/portal/consultas/ifi/listaifi.aspx?lang=es"
                "&nif={nif}&sortExpEmi=FechaRegistroEntrada&sortDirEmi=0")
LISTADO_IFA = BASE + "/portal/consultas/IFA/ListadoIFA?id=0&lang=es&nif={nif}"
DATOS_GENERALES = (BASE + "/Portal/consultas/ee/datosgenerales.aspx"
                   "?nif={nif}&lang=es")
UNIVERSE_DESDE = "2024-01-01"

FROZEN_NIFS = {"A39000013", "A48265169", "A-48010615"}  # SAN/BBVA/IBE

NIF_RE = re.compile(r"^[AVWEXYZ][-\.]?\d{7,8}[-\.]?[A-Z0-9]?$")
MAX_EVENT_DOCS_PER_ISSUER = 3
MAX_LISTADO_PAGES = 3


def jload(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def jwrite(p: Path, obj) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_bytes(json.dumps(
        obj, ensure_ascii=False, sort_keys=True, indent=1
    ).encode("utf-8"))


def norm(s: str) -> str:
    """Uppercase, strip accents, collapse whitespace."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def slug_key(abrev: str) -> str:
    """Deterministic ASCII issuer key from denominación abreviada."""
    s = norm(abrev)
    s = re.sub(r"[^A-Z0-9]+", "_", s).strip("_")
    return s or "ISSUER"


def parse_capital(s: str) -> float | None:
    m = re.search(r"([\d\.]+),(\d+)", s)
    if not m:
        return None
    return float(m.group(1).replace(".", "") + "." + m.group(2))


def store_page(store: EvidenceStore, body: bytes,
               media: str | None = "text/html") -> dict:
    rel, sha, stored = store.store(body, media_type=media)
    return {"evidence_path": rel, "sha256": sha, "stored": stored}


# ---------------------------------------------------------------- step 1
def fetch_universe(sess: PoliteSession, store: EvidenceStore,
                   hasta: str) -> list[dict]:
    """Empty-denomination IFA search -> issuer picker (nif, denomination)."""
    r = sess.get(SEARCH_URL, note="freeze: IFA search form")
    store_page(store, r.content)
    from opencnmv.source.cnmv.discovery import hidden_fields
    data = {**hidden_fields(r.text),
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": "",
            "ctl00$ContentPrincipal$wFechas$fecha_desde": UNIVERSE_DESDE,
            "ctl00$ContentPrincipal$wFechas$fecha_hasta": hasta,
            "ctl00$ContentPrincipal$wFechas$ult_dias": "",
            "ctl00$ContentPrincipal$btnOk": "Buscar"}
    r2 = sess.post(SEARCH_URL, data=data, headers={"Referer": SEARCH_URL},
                   note="freeze: IFA issuer picker (empty denomination)")
    store_page(store, r2.content)
    html = r2.content.decode("utf-8", errors="replace")
    universe = {}
    for val, label in re.findall(
            r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', html):
        val, label = val.strip(), label.strip()
        if NIF_RE.match(val) and label:
            universe[val] = label
    return [{"nif": n, "denomination": d}
            for n, d in sorted(universe.items())]


# ---------------------------------------------------------------- step 2
def fetch_listaifi_default(sess: PoliteSession,
                           store: EvidenceStore) -> dict:
    r = sess.get(LISTAIFI, note="freeze: unfiltered listaifi")
    return store_page(store, r.content)


# ---------------------------------------------------------------- step 3
def fetch_ficha(sess: PoliteSession, store: EvidenceStore,
                nif: str) -> dict:
    """datosgenerales row: nif, lei, denominación abreviada, sector,
    capital."""
    r = sess.get(DATOS_GENERALES.format(nif=nif),
                 note=f"freeze: ficha {nif}")
    page = store_page(store, r.content)
    html = r.content.decode("utf-8", errors="replace")
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        cells = [c for c in cells if c]
        if cells and cells[0].replace("&#45;", "-") == nif:
            return {"nif": nif, "lei": cells[1] if len(cells) > 1 else None,
                    "abrev": cells[2] if len(cells) > 2 else None,
                    "sector": cells[3] if len(cells) > 3 else None,
                    "capital_text": cells[4] if len(cells) > 4 else None,
                    "capital": parse_capital(
                        cells[4] if len(cells) > 4 else ""),
                    "ficha": page}
    return {"nif": nif, "lei": None, "abrev": None, "sector": None,
            "capital_text": None, "capital": None, "ficha": page,
            "identity_unresolved": True}


# ---------------------------------------------------------------- step 4
def _sector_parts(entry: dict) -> tuple[str, str]:
    s = norm(entry.get("sector") or "")
    grp, _, sub = s.partition("/")
    return grp.strip(), sub.strip()


def _is_ft(e): return "TITULIZACION" in _sector_parts(e)[1]


def _is_credit(e):
    g, s = _sector_parts(e)
    return ("FINANCIACION" in g
            and re.search(r"BANC|CAJA|COOPERATIV|CREDITO", s)
            and not _is_ft(e))


def _is_utility(e):
    g, _ = _sector_parts(e)
    return g.startswith("ENERGIA") or "AGUA" in g


def _is_real_estate(e):
    g, s = _sector_parts(e)
    return bool(re.search(r"INMOBILIARIA|SOCIMI|REAL ESTATE", s)
                or re.search(r"INMOBILIARIA", g))


def _is_financial(e):
    return "FINANCIACION" in _sector_parts(e)[0]


def _cap_key(e):
    c = e.get("capital")
    return (c is not None, c or 0.0, e["nif"])


def _top(pool, n):
    return sorted(pool, key=_cap_key, reverse=True)[:n]


def _bottom(pool, n):
    cand = [e for e in pool if e.get("capital")]
    return sorted(cand, key=_cap_key)[:n]


def select_sample(pool: list[dict]) -> dict[str, dict]:
    """Deterministic stratified selection per the README quotas."""
    strata: dict[str, list[dict]] = {}
    remaining = {e["nif"]: e for e in pool
                 if e["nif"] not in FROZEN_NIFS
                 and not e.get("identity_unresolved")}

    def take(name, cands):
        picked = []
        for e in cands:
            if e["nif"] in remaining:
                picked.append(e)
                remaining.pop(e["nif"])
        strata[name] = picked

    take("credit-institutions",
         _top([e for e in remaining.values() if _is_credit(e)], 8))
    take("utilities",
         _top([e for e in remaining.values() if _is_utility(e)], 5))
    take("real-estate-socimi",
         _top([e for e in remaining.values() if _is_real_estate(e)], 6))
    take("securitisation-funds",
         sorted([e for e in remaining.values() if _is_ft(e)],
                key=lambda e: e["nif"])[:2])
    take("large-industrials",
         _top([e for e in remaining.values()
               if not _is_financial(e) and not _is_utility(e)
               and not _is_real_estate(e)], 7))
    take("small-mid-caps",
         _bottom([e for e in remaining.values() if not _is_ft(e)], 8))
    represented = {_sector_parts(e)[0]
                   for lst in strata.values() for e in lst}
    take("residual-sectors",
         sorted([e for e in remaining.values()
                 if _sector_parts(e)[0] not in represented],
                key=lambda e: e["nif"])[:4])

    out: dict[str, dict] = {}
    used_keys = {"SAN", "BBVA", "IBE"}
    for stratum, entries in strata.items():
        for e in entries:
            key = slug_key(e.get("abrev") or e["denomination"])
            base, i = key, 2
            while key in used_keys:
                key, i = f"{base}_{i}", i + 1
            used_keys.add(key)
            out[e["nif"]] = {
                "nif": e["nif"], "key": key,
                "denomination": e["denomination"],
                "abrev": e.get("abrev"), "lei": e.get("lei"),
                "sector": e.get("sector"),
                "capital": e.get("capital"),
                "strata": [stratum]}
    # historical-depth subsample: 2 per main stratum, nif-ascending
    main = ["credit-institutions", "utilities", "real-estate-socimi",
            "large-industrials", "small-mid-caps"]
    for name in main:
        cands = sorted((e["nif"] for e in strata.get(name, [])))
        for nif in cands[:2]:
            out[nif]["strata"].append("historical-depth")
            out[nif]["historical"] = True
    for e in out.values():
        e.setdefault("historical", False)
    return out


# ---------------------------------------------------------------- step 5
SEM_RE = re.compile(r"\b(I{1,2})\s+SEMESTRE\s+DE\s+(\d{4})")


def parse_listaifi(html: str) -> list[dict]:
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        nm = re.search(r"detalleifialdia\.aspx\?nreg=(\d+)", row)
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if nm and cells and re.match(r"\d{2}/\d{2}/\d{4}", cells[0]):
            sm = SEM_RE.search(norm(cells[1] if len(cells) > 1 else ""))
            rows.append({"nreg": nm.group(1), "published": cells[0],
                         "kind": cells[1] if len(cells) > 1 else "",
                         "semester": sm.group(1) if sm else None,
                         "year": int(sm.group(2)) if sm else None})
    return rows


def parse_listadoifa(html: str) -> list[dict]:
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        row = m.group(1)
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if not cells or not re.match(r"^\d{4,6}$", cells[0]):
            continue
        infad = re.findall(
            r"infadicionifa\.aspx\?id=0&amp;nreg=(\d+)&amp;nregaud=(\d+)",
            row)
        rows.append({"registro": cells[0],
                     "period_end": cells[1] if len(cells) > 1 else None,
                     "published": cells[2] if len(cells) > 2 else None,
                     "ampliacion": any(c == "Sí" for c in cells[3:]),
                     "infadicion": [{"nreg": a, "nregaud": b}
                                    for a, b in infad]})
    return rows


def classify_event_doc(html: str) -> str:
    t = norm(html)
    if "SUSTITUCION" in t:
        return "SUBSTITUTION"
    if "CERTIFICACION" in t or "CERTIFICADO" in t:
        return "CERTIFICATE"
    return "OTHER"


def fetch_inventory(sess: PoliteSession, store: EvidenceStore,
                    nif: str, key: str) -> dict:
    inv: dict = {"nif": nif, "key": key, "ipp_rows": [], "ifa_rows": [],
                 "event_docs": []}
    try:
        r = sess.get(LISTAIFI_NIF.format(nif=nif),
                     note=f"freeze: listaifi {key}")
        store_page(store, r.content)
        inv["ipp_rows"] = parse_listaifi(
            r.content.decode("utf-8", errors="replace"))
    except Exception as ex:  # noqa: BLE001 — recorded, not fatal
        inv["ipp_error"] = str(ex)[:200]
    try:
        r = sess.get(LISTADO_IFA.format(nif=nif),
                     note=f"freeze: ListadoIFA {key}")
        store_page(store, r.content)
        inv["ifa_rows"] = parse_listadoifa(
            r.content.decode("utf-8", errors="replace"))
    except Exception as ex:  # noqa: BLE001
        inv["ifa_error"] = str(ex)[:200]
    # event-doc probes: most recent rows carrying infadicion links
    flagged = [row for row in inv["ifa_rows"] if row["infadicion"]]
    for row in flagged[:MAX_EVENT_DOCS_PER_ISSUER]:
        for link in row["infadicion"][:1]:
            url = (BASE + "/portal/consultas/IFA/infadicionifa.aspx"
                   f"?id=0&nreg={link['nreg']}&nregaud={link['nregaud']}")
            try:
                r = sess.get(url, note=f"freeze: event doc {key} "
                                       f"{link['nreg']}")
                store_page(store, r.content)
                inv["event_docs"].append({
                    "nreg": link["nreg"], "nregaud": link["nregaud"],
                    "target_registro": row["registro"],
                    "class": classify_event_doc(
                        r.content.decode("utf-8", errors="replace"))})
            except Exception as ex:  # noqa: BLE001
                inv["event_docs"].append({
                    "nreg": link["nreg"], "nregaud": link["nregaud"],
                    "target_registro": row["registro"],
                    "class": "FETCH_FAILED", "error": str(ex)[:200]})
    return inv


def derive_scope(inv: dict, historical: bool) -> dict:
    """Uniform scope rule from the freeze inventory (README §scope)."""
    periods = sorted({r["period_end"] for r in inv["ifa_rows"]
                      if r.get("period_end")},
                     key=lambda p: (p[-4:], p[3:5], p[:2]), reverse=True)
    slots = sorted({(r["year"], r["semester"]) for r in inv["ipp_rows"]
                    if r.get("year") and r.get("semester")},
                   reverse=True)
    n_esef = 2 if historical else 1
    n_ipp = 4 if historical else 2
    return {"esef_periods": periods[:n_esef],
            "ipp_slots": [[sem, yr] for yr, sem in slots[:n_ipp]]}


def main() -> int:
    sess = PoliteSession(min_delay=MIN_DELAY)
    store = EvidenceStore(FREEZE)
    hasta = utcnow()[:10]
    manifest = new_manifest(
        f"freeze-{utcnow().replace(':', '').replace('-', '')[:15]}",
        {"freeze": True, "window_desde": UNIVERSE_DESDE,
         "window_hasta": hasta}, sess.user_agent, MIN_DELAY)

    universe = fetch_universe(sess, store, hasta)
    jwrite(HERE / "universe.json",
           {"window": {"desde": UNIVERSE_DESDE, "hasta": hasta},
            "count": len(universe), "issuers": universe})
    print(f"universe: {len(universe)} issuers")

    listaifi_page = fetch_listaifi_default(sess, store)

    pool = []
    for i, u in enumerate(universe):
        f = fetch_ficha(sess, store, u["nif"])
        f["denomination"] = u["denomination"]
        pool.append(f)
        if (i + 1) % 50 == 0:
            print(f"  fichas: {i + 1}/{len(universe)}")
    unresolved = [e["nif"] for e in pool if e.get("identity_unresolved")]
    print(f"fichas: {len(pool)} ({len(unresolved)} unresolved)")

    sample = select_sample(pool)
    strata_counts = {}
    for e in sample.values():
        for s in e["strata"]:
            strata_counts[s] = strata_counts.get(s, 0) + 1
    print(f"sample: {len(sample)} issuers; strata={strata_counts}")

    inventories = {}
    for nif, e in sorted(sample.items()):
        inv = fetch_inventory(sess, store, nif, e["key"])
        inv["scope"] = derive_scope(inv, e["historical"])
        e["scope"] = inv["scope"]
        inv["event_classes"] = sorted(
            {d["class"] for d in inv["event_docs"]})
        inventories[nif] = inv
        print(f"  {e['key']}: ifa={len(inv['ifa_rows'])} "
              f"ipp={len(inv['ipp_rows'])} events={inv['event_classes']}")

    jwrite(HERE / "sample.json", {
        "format": "ISSUER_REGISTRY_V1",
        "frozen_at": utcnow(),
        "window": {"desde": UNIVERSE_DESDE, "hasta": hasta},
        "excluded_frozen_corpus": sorted(FROZEN_NIFS),
        "strata_counts": strata_counts,
        "issuers": {nif: {k: v for k, v in e.items()}
                    for nif, e in sorted(sample.items())}})
    jwrite(HERE / "expected_inventory.json", {
        "frozen_at": utcnow(),
        "issuers": {nif: inv for nif, inv in sorted(inventories.items())}})

    manifest["fetch_log"] = sess.fetch_log
    manifest["freeze"] = {
        "universe_count": len(universe),
        "identity_unresolved": unresolved,
        "listaifi_default": listaifi_page,
        "sample_size": len(sample),
        "strata_counts": strata_counts,
        "finished_at": utcnow()}
    store.finish_run(manifest)
    jwrite(HERE / "freeze_manifest.json", manifest)
    print(f"freeze done: {len(sess.fetch_log)} requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
