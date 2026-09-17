"""Polite sequential session + write-once content-addressed evidence store.

``PoliteSession`` is the single network surface: one requests.Session, a
declared User-Agent, and a minimum inter-request delay. It also passes
for a plain session where helpers such as
``source.cnmv.retrieval.fetch_document`` call ``s.get(...)`` — every
request lands in the fetch log.

``EvidenceStore`` preserves raw bytes under
``<evidence-dir>/artifacts/<sha256>.<ext>`` (write-once, content
addressed: re-fetched identical bytes are deduplicated; a byte that
differs under the same logical name simply gets its own sha path — raw
is never overwritten) and appends every transfer to the run manifest's
fetch log.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from typing import cast

import requests

from opencnmv.capture.contract import (CAPTURE_MANIFEST_FORMAT,
                                       MIN_DELAY_S, USER_AGENT,
                                       CaptureError)
from opencnmv.source.cnmv import retrieval


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ext_of(body: bytes, media_type: str | None) -> str:
    if body[:2] == b"PK":
        return ".zip"
    if body[:4] == b"%PDF":
        return ".pdf"
    head = body[:512].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<xbrl"):
        return ".xbrl"
    if b"<html" in head:
        return ".html"
    if media_type and "xml" in media_type:
        return ".xml"
    return ".bin"


class PoliteSession:
    """requests.Session wrapper: sequential, declared UA, min delay.

    ``get`` returns the raw ``requests.Response`` after enforcing the
    delay, so it is a drop-in for helpers that call ``s.get``. Every
    completed request appends to ``fetch_log``.
    """

    def __init__(self, *, min_delay: float = MIN_DELAY_S,
                 user_agent: str = USER_AGENT,
                 session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self.min_delay = min_delay
        self._last_request = 0.0
        self.fetch_log: list[dict] = []

    def _throttle(self) -> None:
        wait = self.min_delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, *, note: str = "", **kw) -> requests.Response:
        self._throttle()
        t0 = time.monotonic()
        try:
            r = self.session.get(url, timeout=kw.pop("timeout", 120), **kw)
        except requests.RequestException as ex:
            raise CaptureError(f"GET {url} failed: {ex}") from ex
        self._last_request = time.monotonic()
        if r.status_code != 200:
            raise CaptureError(
                f"GET {url} -> HTTP {r.status_code} ({note or 'request'})")
        self.fetch_log.append({
            "note": note, "source_url": url, "final_url": r.url,
            "http_status": r.status_code,
            "media_type": r.headers.get("Content-Type"),
            "byte_size": len(r.content), "sha256": hashlib.sha256(
                r.content).hexdigest(),
            "retrieved_at": utcnow(),
            "elapsed_ms": int((time.monotonic() - t0) * 1000)})
        return r

    def post(self, url: str, *, data: dict, note: str = "",
             **kw) -> requests.Response:
        self._throttle()
        t0 = time.monotonic()
        try:
            r = self.session.post(url, data=data,
                                  timeout=kw.pop("timeout", 180), **kw)
        except requests.RequestException as ex:
            raise CaptureError(f"POST {url} failed: {ex}") from ex
        self._last_request = time.monotonic()
        if r.status_code != 200:
            raise CaptureError(
                f"POST {url} -> HTTP {r.status_code} ({note or 'request'})")
        self.fetch_log.append({
            "note": note, "source_url": url, "final_url": r.url,
            "http_status": r.status_code,
            "media_type": r.headers.get("Content-Type"),
            "byte_size": len(r.content), "sha256": hashlib.sha256(
                r.content).hexdigest(),
            "retrieved_at": utcnow(),
            "elapsed_ms": int((time.monotonic() - t0) * 1000)})
        return r

    def fetch_document(self, token: str, *, note: str = "",
                       max_bytes: int = 128 * 1024 * 1024,
                       max_seconds: float = 600) -> tuple[bytes, str, str]:
        """Bounded verdocumento download through the throttle.

        Returns (body, media_type, source_url). Retrieval limits raise
        CaptureError — fail closed per the G2-F contract.
        """
        url = retrieval.VERDOC.format(tok=token)
        self._throttle()
        t0 = time.monotonic()
        try:
            body, media = retrieval.fetch_document(
                cast(requests.Session, _ThrottledAdapter(self)), token,
                max_bytes=max_bytes, max_seconds=max_seconds)
        except (requests.RequestException, ValueError) as ex:
            raise CaptureError(
                f"document {token[:24]}… failed: {ex}") from ex
        self.fetch_log.append({
            "note": note, "source_url": url, "final_url": url,
            "http_status": 200, "media_type": media,
            "byte_size": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "retrieved_at": utcnow(),
            "elapsed_ms": int((time.monotonic() - t0) * 1000)})
        return body, media, url


class _ThrottledAdapter:
    """Inner adapter handed to retrieval.fetch_document: throttles the
    streaming GET it performs so the byte-cap logic stays in one place."""

    def __init__(self, outer: PoliteSession):
        self._outer = outer

    def get(self, url: str, **kw):
        self._outer._throttle()
        r = self._outer.session.get(url, **kw)
        self._outer._last_request = time.monotonic()
        if r.status_code != 200:
            r.close()
            raise CaptureError(f"GET {url} -> HTTP {r.status_code}")
        return _ResponseCtx(r)


class _ResponseCtx:
    def __init__(self, r: requests.Response):
        self._r = r

    def __enter__(self):
        return self._r

    def __exit__(self, *exc):
        self._r.close()
        return False


class EvidenceStore:
    """Write-once content-addressed artifact store + run manifests.

    Layout::

        <evidence-dir>/
            artifacts/<sha256>.<ext>
            runs/<capture_id>/manifest.json
            latest.json          -> {"capture_id": ...}  (small pointer)
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.artifacts_dir = self.root / "artifacts"
        self.runs_dir = self.root / "runs"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def store(self, body: bytes, *, media_type: str | None = None
              ) -> tuple[str, str, bool]:
        """Preserve raw bytes. Returns (evidence_path, sha256, stored).

        Write-once: an existing object with the same sha is reused
        (``stored=False``); differing bytes land under their own sha —
        never an overwrite.
        """
        sha = hashlib.sha256(body).hexdigest()
        rel = f"artifacts/{sha}{_ext_of(body, media_type)}"
        path = self.root / rel
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise CaptureError(f"evidence object corrupt: {rel}")
            return rel, sha, False
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return rel, sha, True

    def finish_run(self, manifest: dict) -> Path:
        """Persist the run manifest; point latest.json at it."""
        cid = manifest["capture_id"]
        run_dir = self.runs_dir / cid
        run_dir.mkdir(parents=True, exist_ok=True)
        mp = run_dir / "manifest.json"
        mp.write_bytes(json.dumps(manifest, ensure_ascii=False,
                                  sort_keys=True, indent=1)
                       .encode("utf-8"))
        (self.root / "latest.json").write_bytes(json.dumps(
            {"capture_id": cid}, indent=1).encode("utf-8"))
        return mp


def new_manifest(capture_id: str, scope: dict, user_agent: str,
                 min_delay: float) -> dict:
    return {"capture_manifest": CAPTURE_MANIFEST_FORMAT,
            "capture_id": capture_id,
            "captured_at": utcnow(),
            "user_agent": user_agent,
            "min_delay_s": min_delay,
            "scope": scope,
            "fetch_log": [],
            "esef_views": [],
            "ipp_filings": [],
            "infadicion_walks": [],
            "warnings": []}


def load_latest_manifest(root: Path, run: str | None = None
                         ) -> tuple[dict, Path]:
    """Load a capture manifest from an evidence dir.

    ``run`` pins a specific capture id; otherwise the newest run is used
    (``latest.json`` pointer, with a timestamp fallback).
    """
    root = Path(root)
    runs = root / "runs"
    if run is None:
        ptr = root / "latest.json"
        if ptr.is_file():
            run = json.loads(ptr.read_text(encoding="utf-8"))["capture_id"]
        else:
            cands = sorted(p.name for p in runs.iterdir() if p.is_dir())
            if not cands:
                raise CaptureError(f"no capture runs under {runs}")
            run = cands[-1]
    mp = runs / run / "manifest.json"
    if not mp.is_file():
        raise CaptureError(f"capture manifest not found: {mp}")
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    if manifest.get("capture_manifest") != CAPTURE_MANIFEST_FORMAT:
        raise CaptureError(f"{mp}: capture_manifest != "
                           f"{CAPTURE_MANIFEST_FORMAT}")
    return manifest, mp


def slug(*parts: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", "-".join(parts))
