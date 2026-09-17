"""CNMV discovery — official surfaces only.

busqueda?id=25 (IFA annual reports) incl. the entity-picker postback, and
infadicionifa event history. Raw served bytes are what callers must
preserve; helpers return both bytes and parsed rows.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

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


class IssuerSelectionError(ValueError):
    def __init__(self, response: requests.Response):
        super().__init__("Issuer picker has no unique matching selection")
        self.response = response
        self.body = response.content


class _IssuerPicker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.present = False
        self.active = False
        self.options = []
        self.option = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.active = attrs.get("name") == (
                "ctl00$ContentPrincipal$wbusqueda$lstSeleccion")
            self.present = self.present or self.active
        elif tag == "option" and self.active:
            self._finish_option()
            if attrs.get("value") and "disabled" not in attrs:
                self.option = [attrs["value"], ""]

    def handle_data(self, data):
        if self.option is not None:
            self.option[1] += data

    def handle_endtag(self, tag):
        if tag == "option":
            self._finish_option()
        elif tag == "select":
            self._finish_option()
            self.active = False

    def _finish_option(self):
        if self.option is not None:
            self.options.append(tuple(self.option))
            self.option = None


def search_ifa(s: requests.Session, denom: str, lang: str,
               desde: str, hasta: str, *, issuer_value: str | None = None) -> bytes:
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
    picker = _IssuerPicker()
    picker.feed(r2.text)
    picker.close()
    if picker.present:
        if issuer_value is not None:
            matches = [o for o in picker.options if o[0] == issuer_value]
        elif len(picker.options) == 1:
            matches = picker.options
        else:
            name = " ".join(denom.split()).casefold()
            matches = [o for o in picker.options
                       if " ".join(o[1].split()).casefold() == name]
        if len(matches) != 1:
            raise IssuerSelectionError(r2)
        data2 = {**hidden_fields(r2.text),
                 "ctl00$ContentPrincipal$wbusqueda$lstSeleccion": matches[0][0],
                 "ctl00$ContentPrincipal$wbusqueda$btnSeleccionar":
                     "Seleccionar" if lang == "es" else "Select"}
        r3 = s.post(url, data=data2, timeout=180,
                    headers={"Referer": url})
        r3.raise_for_status()
        remaining = _IssuerPicker()
        remaining.feed(r3.text)
        remaining.close()
        if remaining.present:
            raise IssuerSelectionError(r3)
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
