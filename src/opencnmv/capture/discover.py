"""Live CNMV discovery for the frozen corpus (official surfaces only).

Surfaces used:

  * ``busqueda?id=25``      ESEF/IFA registry, once per UI language —
                            per-language views are what distinguish a real
                            submitted variant from a FALLBACK resolution.
  * ``listaifi``            IPP listing (nif-scoped, unambiguous).
  * ``detalleifialdia``     IPP detail page -> descargaxbrlipp guid.
  * ``infadicionifa``       version-event history per IFA registry row.
  * ``verdocumento``        document/artifact bytes (via fetch_document).

Everything downloaded is preserved write-once through ``EvidenceStore``
before any parsing. Discovery never infers: unexpected shapes raise
``CaptureError`` (-> CLI exit 7).
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import cast

import requests

from opencnmv.capture.contract import (ESEF_PERIODS, ESEF_TOKEN_ROLES,
                                       IPP_SLOTS, CaptureError)
from opencnmv.capture.fetch import EvidenceStore, PoliteSession
from opencnmv.provenance.hashes import artifact_set_id
from opencnmv.source.cnmv import discovery as cn

LISTAIFI = cn.BASE + "/portal/consultas/ifi/listaifi?lang=es&nif={nif}"
DETALLE = cn.BASE + "/portal/aldia/detalleifialdia.aspx?nreg={nreg}"
DL_IPP = (cn.BASE + "/portal/consultas/wuc/descargaxbrlipp"
          ".ashx?t=%7b{guid}%7d")

_IPP_SLOT_RE = re.compile(r"(?i)\b(II|I)\s+semestre\s+de\s+(\d{4})")
_GUID_RE = re.compile(
    rb"descargaxbrlipp\.ashx\?t=\{([0-9a-fA-F-]{36})\}")


def ipp_slot_label(sem: str, year: int) -> str:
    return f"H{1 if sem == 'I' else 2}-{year}"


def ipp_slot_period_end(sem: str, year: int) -> str:
    return f"{year}-06-30" if sem == "I" else f"{year}-12-31"


def _lang_tags(pkg: bytes) -> set[str]:
    """All ``-{es|en}`` root-dir tags inside a report package."""
    try:
        z = zipfile.ZipFile(io.BytesIO(pkg))
    except zipfile.BadZipFile:
        raise CaptureError("ESEF package is not a zip")
    tags = set()
    for name in z.namelist():
        if "/" in name:
            m = re.search(r"-(es|en)$", name.split("/", 1)[0])
            if m:
                tags.add(m.group(1))
    return tags


def _store_bytes(store: EvidenceStore, body: bytes,
                 media_type: str | None,
                 sess: PoliteSession | None = None) -> dict:
    rel, sha, stored = store.store(body, media_type=media_type)
    rec = {"sha256": sha, "byte_size": len(body),
           "media_type": media_type, "evidence_path": rel,
           "deduplicated": not stored}
    if sess is not None and sess.fetch_log:
        last = sess.fetch_log[-1]
        rec["retrieved_at"] = last.get("retrieved_at")
        rec["http_status"] = last.get("http_status")
        rec["source_url"] = last.get("source_url")
    return rec


def discover_esef(sess: PoliteSession, store: EvidenceStore,
                  nif: str, issuer: dict, desde: str, hasta: str,
                  manifest: dict,
                  esef_periods=ESEF_PERIODS) -> None:
    """Dual-language IFA views for one issuer; appends esef_views and
    infadicion_walks entries to ``manifest``.

    Per registry row we preserve the search page, the report-package
    bytes, and every infadicionifa event document.
    """
    key = issuer["key"]
    views: dict[tuple[str, str], dict] = {}
    for lang in ("es", "en"):
        try:
            body = cn.search_ifa(cast(requests.Session, sess),
                                 issuer["denomination"], lang,
                                 desde, hasta)
        except cn.IssuerSelectionError as ex:
            raise CaptureError(
                f"{key}: issuer picker ambiguous in lang={lang} "
                f"({ex})") from ex
        page = _store_bytes(store, body, "text/html", sess)
        rows = cn.parse_rows(body.decode("utf-8", errors="replace"))
        served_periods = {row["cells"][1] for row in rows
                          if len(row["cells"]) >= 2}
        for declared in esef_periods:
            if declared not in served_periods:
                # declared scope period not present in the served
                # registry (delisted issuer, window edge, ...) — the
                # omission is documented, never silent
                manifest["warnings"].append(
                    f"{key}/{lang}: declared scope period {declared!r} "
                    f"absent from served registry rows")
        for row in rows:
            cells = row["cells"]
            if len(cells) < 2:
                manifest["warnings"].append(
                    f"{key}/{lang}: registry row without period cell")
                continue
            registro, period = cells[0], cells[1]
            if period not in esef_periods:
                # out-of-scope row: recorded in the inventory, never
                # silently captured (declared scope).
                manifest["warnings"].append(
                    f"{key}/{lang}: registro {registro} period "
                    f"{period!r} outside declared scope — not captured")
                continue
            if (registro, lang) in views:
                manifest["warnings"].append(
                    f"{key}/{lang}: duplicate registry row for "
                    f"{registro} (first kept)")
                continue
            views[(registro, lang)] = {
                "issuer_key": key, "nif": nif, "registro": registro,
                "requested_ui_language": lang,
                "registry_row": {"cells": cells,
                                 "tokens": row["tokens"],
                                 "infadicion": row["infadicion"]},
                "search_page": page}

    registros = sorted({r for r, _ in views},
                       key=lambda r: (views[(r, "es")]["registry_row"]
                                      ["cells"][1] if (r, "es") in views
                                      else "", r))
    for registro in registros:
        for lang in ("es", "en"):
            v = views.get((registro, lang))
            if v is None:
                manifest["warnings"].append(
                    f"{key}: registro {registro} has no {lang} view")
                continue
            toks = v["registry_row"]["tokens"]
            if not toks:
                # In-scope registry row published without any document
                # links (e.g. securitisation funds: audit PDF and
                # infadicion only, empty ZIP/XBRL cell). Source state,
                # not a pipeline failure — classify, never abort.
                v["status"] = "NO_PACKAGE_IN_ROW"
                v["resolved_submission_language"] = None
                v["resolution_mode"] = "UNRESOLVED_NO_PACKAGE"
                manifest["warnings"].append(
                    f"{key}/{registro}/{lang}: registry row has no "
                    f"verdocumento tokens — no package published; "
                    f"view classified UNRESOLVED_NO_PACKAGE")
                manifest["esef_views"].append(v)
                continue
            if len(toks) != len(ESEF_TOKEN_ROLES):
                manifest["warnings"].append(
                    f"{key}/{registro}/{lang}: {len(toks)} verdocumento "
                    f"tokens (expected {len(ESEF_TOKEN_ROLES)}) — "
                    f"roles unmapped, raw tokens preserved")
            v["document_locators"] = (
                dict(zip(ESEF_TOKEN_ROLES, toks))
                if len(toks) == len(ESEF_TOKEN_ROLES)
                else {"raw_tokens": toks})
            # last token on the row is the report package (G1-B order).
            body, media, url = sess.fetch_document(
                toks[-1], note=f"esef-pkg-{key}-{registro}-{lang}")
            rec = _store_bytes(store, body, media, sess)
            rec["source_url"] = url
            v["package"] = rec
            try:
                tags = _lang_tags(body)
            except CaptureError:
                # the registry serves a non-zip document for this view
                # (single-token rows, visual XHTML reports, ...). The
                # bytes are preserved above; the view is classified
                # UNRESOLVED instead of aborting the whole capture.
                v["status"] = "PACKAGE_NOT_ZIP"
                v["resolved_submission_language"] = None
                v["resolution_mode"] = "UNRESOLVED_PACKAGE"
                manifest["warnings"].append(
                    f"{key}/{registro}/{lang}: report package is not "
                    f"a zip ({len(body)} bytes, {media}) — view "
                    f"classified UNRESOLVED_PACKAGE")
                manifest["esef_views"].append(v)
                continue
            if len(tags) != 1:
                v["status"] = "PACKAGE_AMBIGUOUS_LANG"
                v["resolved_submission_language"] = None
                v["resolution_mode"] = "UNRESOLVED_PACKAGE"
                manifest["warnings"].append(
                    f"{key}/{registro}/{lang}: package language tags "
                    f"{sorted(tags)} — cannot resolve submission "
                    f"language; view classified UNRESOLVED_PACKAGE")
                manifest["esef_views"].append(v)
                continue
            resolved = sorted(tags)[0]
            v["resolved_submission_language"] = resolved
            v["resolution_mode"] = ("SUBMITTED_VARIANT" if resolved == lang
                                    else f"FALLBACK_TO_{resolved.upper()}")
            v["variant_artifact_set_id"] = artifact_set_id(
                [{"role": "ESEF_PACKAGE_ZIP_XBRL",
                  "sha256": rec["sha256"]}])
            manifest["esef_views"].append(v)

        # version-event history (once per registro, es surface)
        inf_links = views.get((registro, "es"), {}).get(
            "registry_row", {}).get("infadicion", [])
        if not inf_links:
            continue
        nreg, nregaud = cn.nreg_from_infadicion(inf_links[0])
        if not nreg or not nregaud:
            manifest["warnings"].append(
                f"{key}/{registro}: infadicion link without nreg/nregaud")
            continue
        ev_page = sess.get(cn.INFADICION.format(lang="es", nreg=nreg,
                                                nregaud=nregaud),
                           note=f"infadicionifa-{nregaud}")
        prec = _store_bytes(store, ev_page.content, "text/html", sess)
        rows = []
        for ev in cn.parse_event_rows(
                ev_page.content.decode("utf-8", errors="replace")):
            entry = {"cells": ev["cells"], "tokens": ev["tokens"],
                     "doc_artifacts": []}
            for tok in ev["tokens"]:
                body, media, url = sess.fetch_document(
                    tok, note=f"event-doc-{nregaud}")
                doc = _store_bytes(store, body, media, sess)
                doc["source_url"] = url
                doc["artifact_id"] = "sha256:" + doc["sha256"]
                entry["doc_artifacts"].append(doc)
            rows.append(entry)
        manifest["infadicion_walks"].append(
            {"issuer_key": key, "registro": registro,
             "nreg": nreg, "nregaud": nregaud, "page": prec,
             "events": rows})


def discover_ipp(sess: PoliteSession, store: EvidenceStore,
                 nif: str, issuer: dict, manifest: dict,
                 ipp_slots=IPP_SLOTS) -> None:
    """Declared IPP slots for one issuer; appends ipp_filings entries."""
    key = issuer["key"]
    r = sess.get(LISTAIFI.format(nif=nif), note=f"listaifi-{key}")
    page = _store_bytes(store, r.content,
                        r.headers.get("Content-Type"), sess)
    found: dict[tuple[str, int], dict] = {}
    for row in cn.parse_listaifi_rows(
            r.content.decode("utf-8", errors="replace")):
        m = _IPP_SLOT_RE.search(row["kind"])
        if not m:
            continue
        sem, year = m.group(1).upper(), int(m.group(2))
        if (sem, year) in found:
            manifest["warnings"].append(
                f"{key}: duplicate listaifi row for "
                f"{ipp_slot_label(sem, year)} (first kept)")
            continue
        found[(sem, year)] = {"nreg": row["nreg"],
                              "published": row["published"]}

    for sem, year in ipp_slots:
        slot = ipp_slot_label(sem, year)
        rec = {"issuer_key": key, "nif": nif, "slot": slot,
               "semester": sem, "year": year,
               "period_end": ipp_slot_period_end(sem, year),
               "listaifi_page": page}
        manifest["ipp_filings"].append(rec)
        li = found.get((sem, year))
        if li is None:
            rec["status"] = "NOT_FOUND"
            manifest["warnings"].append(
                f"{key}: {slot} not listed in listaifi")
            continue
        rec["nreg"] = li["nreg"]
        rec["published"] = li["published"]
        det = sess.get(DETALLE.format(nreg=li["nreg"]),
                       note=f"detalle-{key}-{slot}")
        dprec = _store_bytes(store, det.content,
                             det.headers.get("Content-Type"), sess)
        rec["detail_page"] = dprec
        g = _GUID_RE.search(det.content)
        if not g:
            rec["status"] = "GUID_NOT_FOUND"
            manifest["warnings"].append(
                f"{key}/{slot}: no descargaxbrlipp guid in detalle page")
            continue
        guid = g.group(1).decode()
        rec["download_guid"] = guid
        body = sess.get(DL_IPP.format(guid=guid),
                        note=f"ipp-{key}-{slot}").content
        art = _store_bytes(store, body, "text/xml", sess)
        art["source_url"] = DL_IPP.format(guid=guid)
        art["artifact_id"] = "sha256:" + art["sha256"]
        rec["artifact"] = art
        rec["status"] = "CAPTURED"


def run_discovery(sess: PoliteSession, store: EvidenceStore,
                  nifs: list[str], families: set[str],
                  desde: str, hasta: str,
                  registry: dict | None = None) -> dict:
    """Full declared-scope discovery; returns the capture manifest.

    ``registry`` maps nif -> issuer entry (key/denomination/lei, optional
    per-issuer ``scope``); it defaults to the frozen G2 registry.
    """
    from opencnmv.capture.contract import ISSUERS

    from opencnmv.capture.fetch import new_manifest, utcnow

    reg = ISSUERS if registry is None else registry

    def _scope_of(issuer: dict) -> dict:
        s = issuer.get("scope") or {}
        return {"esef_periods": list(
                    s.get("esef_periods") or ESEF_PERIODS),
                "ipp_slots": [tuple(sl) for sl in
                              (s.get("ipp_slots") or IPP_SLOTS)]}

    issuer_scopes = {n: _scope_of(reg[n]) for n in nifs}
    scope = {"issuers": [{"nif": n, "key": reg[n]["key"],
                          "denomination": reg[n].get("denomination"),
                          "lei": reg[n].get("lei"),
                          "esef_periods": issuer_scopes[n]
                          ["esef_periods"],
                          "ipp_slots": [ipp_slot_label(s, y) for s, y in
                                        issuer_scopes[n]["ipp_slots"]]}
                         for n in nifs],
             "families": sorted(families),
             "search_from": desde, "search_to": hasta,
             "ipp_slots": sorted({ipp_slot_label(s, y)
                                  for n in nifs for s, y in
                                  issuer_scopes[n]["ipp_slots"]}),
             "esef_periods": sorted({p for n in nifs for p in
                                     issuer_scopes[n]
                                     ["esef_periods"]})}
    cid = "cap-" + re.sub(r"[^0-9]", "", utcnow())
    manifest = new_manifest(cid, scope, sess.user_agent, sess.min_delay)

    for nif in nifs:
        issuer = reg[nif]
        isc = issuer_scopes[nif]
        if "ipp" in families:
            discover_ipp(sess, store, nif, issuer, manifest,
                         ipp_slots=isc["ipp_slots"])
        if "ifa" in families:
            discover_esef(sess, store, nif, issuer, desde, hasta,
                          manifest,
                          esef_periods=isc["esef_periods"])
    manifest["fetch_log"] = sess.fetch_log
    return manifest
