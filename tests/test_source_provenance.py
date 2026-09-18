import itertools
import unittest
from unittest.mock import Mock, patch

import requests

from opencnmv.source.cnmv.discovery import IssuerSelectionError, search_ifa
from opencnmv.source.cnmv.retrieval import fetch_document


def _stream_response(chunks, headers=None):
    response = Mock()
    response.headers = headers or {}
    response.iter_content.return_value = iter(chunks)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


class RetrievalTests(unittest.TestCase):
    def test_fetch_document_streams_and_reports_media_type(self):
        session = Mock()
        session.get.return_value = _stream_response(
            [b"abc", b"def"], {"Content-Type": "application/zip"})
        body, media = fetch_document(session, "tok")
        self.assertEqual(body, b"abcdef")
        self.assertEqual(media, "application/zip")
        self.assertEqual(session.get.call_args.kwargs.get("stream")
                         or session.get.call_args[1].get("stream"), True)

    def test_fetch_document_enforces_max_bytes(self):
        session = Mock()
        session.get.return_value = _stream_response(
            [b"x" * 10, b"y" * 10], {"Content-Length": "20"})
        with self.assertRaises(ValueError):
            fetch_document(session, "tok", max_bytes=15)

    def test_fetch_document_rejects_invalid_limits(self):
        session = Mock()
        with self.assertRaises(ValueError):
            fetch_document(session, "tok", max_bytes=0)
        with self.assertRaises(ValueError):
            fetch_document(session, "tok", max_seconds=float("inf"))

    def test_fetch_document_enforces_deadline(self):
        session = Mock()
        session.get.return_value = _stream_response([b"x" * 100] * 100)
        clock = itertools.chain([0.0], itertools.repeat(100.0))
        with patch("opencnmv.source.cnmv.retrieval.time.monotonic",
                   side_effect=lambda: next(clock)):
            with self.assertRaises(requests.Timeout):
                fetch_document(session, "tok", max_seconds=5.0)


class DiscoveryTests(unittest.TestCase):
    def test_ambiguous_picker_rejected_with_evidence(self):
        body = (
            '<select name="ctl00$ContentPrincipal$wbusqueda$lstSeleccion">'
            '<option value="one">BANCO SANTANDER, S.A.</option>'
            '<option value="two">BANCO SANTANDER OTHER, S.A.</option>'
            '</select><input name="btnSeleccionar">'
        ).encode()
        response = Mock(text=body.decode(), content=body)
        session = Mock()
        session.get.return_value = Mock(text="")
        session.post.return_value = response
        with self.assertRaises(IssuerSelectionError) as caught:
            search_ifa(session, "BANCO SANTANDER", "es", "2024-01-01", "2026-09-30")
        self.assertEqual(caught.exception.body, body)
        self.assertEqual(session.post.call_count, 1)

    def test_denomination_html_entities_unescaped_on_the_wire(self):
        # Registry denominations parsed from CNMV HTML may carry verbatim
        # entities (&#209;, &amp;). Posting them literally trips ASP.NET
        # request validation (HTTP 400) and breaks picker matching.
        body = b"<html><body>results</body></html>"
        response = Mock(text=body.decode(), content=body)
        session = Mock()
        session.get.return_value = Mock(text="")
        session.post.return_value = response
        search_ifa(session, "LINEA DIRECTA, S.A., COMPA&#209;IA DE SEGUROS",
                   "es", "2024-01-01", "2026-09-30")
        posted = session.post.call_args.kwargs["data"][
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion"]
        self.assertEqual(posted, "LINEA DIRECTA, S.A., COMPA\u00d1IA DE SEGUROS")
