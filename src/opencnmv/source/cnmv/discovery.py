"""CNMV discovery — official surfaces only.

busqueda?id=25 (IFA annual reports) incl. the entity-picker postback, and
infadicionifa event history. Raw served bytes are what callers must
preserve; helpers return both bytes and parsed rows.
"""
from __future__ import annotations

import re

import requests

BASE = "https://www.cnmv.es"
SEARCH_IFA = BASE + "/Portal/consultas/busqueda?id=25&lang={lang}"
INFADICION = (BASE + "/portal/consultas/ifa/infadicionifa"
              "?id=0&lang={lang}&nreg={nreg}&nregaud={nregaud}")
UA = {"User-Agent": "OpenCNMV/0.1 (canonical capture)"}


def hidden_fields(html: str) -> dict:
    f = {}
    for m in re.finditer(r"<input[^>]*>", html):
        tag = m.group(0)
        n = re.search(r'name="([^"]*)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n and ("VIEWSTATE" in n.group(1) or "EVENT" in n.group(1)):
            f[n.group(1)] = v.group(1) if v else ""
    return f


def search_ifa(s: requests.Session, denom: str, lang: str,
               desde: str, hasta: str) -> bytes:
    """busqueda?id=25 POST, resolving the entity picker if CNMV returns one.
    Returns raw served bytes."""
    url = SEARCH_IFA.format(lang=lang)
    r = s.get(url, timeout=60)
    r.raise_for_status()
    data = {**hidden_fields(r.text),
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion": denom,
            "ctl00$ContentPrincipal$wFechas$fecha_desde": desde,
            "ctl00$ContentPrincipal$wFechas$fecha_hasta": hasta,
            "ctl00$ContentPrincipal$wFechas$ult_dias": "",
            "ctl00$ContentPrincipal$btnOk":
                "Search" if lang == "en" else "Buscar"}
    r2 = s.post(url, data=data, timeout=180, headers={"Referer": url})
    r2.raise_for_status()
    if "lstSeleccion" in r2.text and "btnSeleccionar" in r2.text:
        opts = re.findall(
            r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', r2.text)
        pick = next((o for o in opts if "S.A." in o[1].upper()),
                    opts[-1] if opts else None)
        if pick:
            data2 = {**hidden_fields(r2.text),
                     "ctl00$ContentPrincipal$wbusqueda$lstSeleccion": pick[0],
                     "ctl00$ContentPrincipal$wbusqueda$btnSeleccionar":
                         "Seleccionar" if lang == "es" else "Select"}
            r3 = s.post(url, data=data2, timeout=180,
                        headers={"Referer": url})
            r3.raise_for_status()
            return r3.content
    return r2.content


def infadicionifa(s: requests.Session, nreg: str, nregaud: str,
                  lang: str) -> bytes:
    r = s.get(INFADICION.format(lang=lang, nreg=nreg, nregaud=nregaud),
              timeout=60)
    r.raise_for_status()
    return r.content


def parse_rows(html: str) -> list[dict]:
    """busqueda result rows: cells + verdocumento tokens + infadicion link."""
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
        if cells and cells[0].isdigit():
            toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", m.group(1))
            inf = re.findall(r"infadicionifa[^\"']+", m.group(1))
            rows.append({"cells": cells,
                         "tokens": [t.replace("&amp;", "&") for t in toks],
                         "infadicion": [i.replace("&amp;", "&")
                                        for i in inf]})
    return rows


def parse_event_rows(html: str) -> list[dict]:
    """infadicionifa event table: dated rows + doc tokens.

    NOTE: the event type column is a UI label — G1-D proved a substitution
    can be labelled 'otros'. Labels are evidence, never authority."""
    out = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>|\s+", " ", t).strip()
                 for t in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)]
        toks = re.findall(r"verdocumento/ver\?e=([^\"']+)", m.group(1))
        if cells and re.match(r"\d{2}/\d{2}/\d{4}", cells[0]):
            out.append({"cells": cells,
                        "tokens": [t.replace("&amp;", "&") for t in toks]})
    return out


def nreg_from_infadicion(link: str):
    m = re.search(r"nreg=(\d+)&(?:amp;)?nregaud=(\d+)",
                  link.replace("&amp;", "&"))
    return (m.group(1), m.group(2)) if m else (None, None)
