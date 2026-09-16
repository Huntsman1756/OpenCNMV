"""Thin adapter over Arelle — the authoritative XBRL parser.

OpenCNMV does not implement XBRL semantics; this module only configures an
offline Arelle session over preserved bytes and exposes the loaded model.
Taxonomy resolution comes from caller-pinned taxonomy packages, never the
network or the machine-level Arelle web cache.

Hard rules enforced here (derived from G0 evidence):
  * Arelle version is CHECKED at runtime, not declared (R11/R12 pinned
    2.44.0; a different version aborts rather than parse silently).
  * One Session/Cntlr per filing — taxonomy DTSes are never shared across
    loads (R11: ESEF rewrite overlap makes concurrent loads unsafe).
  * ``internetConnectivity="offline"`` — no network, no cache fallback.
  * Arelle 2.44.0 cannot lexically validate the ~8 MB base64Binary IPP
    facts (nested-quantifier regex -> MemoryError; identical regex in
    2.45.0). A linear-time equivalent shim is installed, gated on the
    EXACT upstream pattern fingerprint — fail-closed, never a generic
    monkey-patch.
  * The raw IPP artefacts are XML instances stored with a ``.zip``
    suffix; Arelle would treat them as archives. They are fed through a
    SHA-verified ``.xbrl`` copy while the preserved bytes stay untouched.
"""
from __future__ import annotations

import base64, hashlib, inspect, logging, shutil, time
from dataclasses import dataclass, field
from pathlib import Path

ARELLE_VERSION = "2.44.0"

_B64SET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
_WSSET = frozenset(" \t\n\r")
_B64_R1 = frozenset("AEIMQUYcgkosw048")   # allowed char before single '='
_B64_R2 = frozenset("AQgw")              # allowed char before '=='
_ORIG_B64_PATTERN_SHA256 = "CB74F11E4811A3159BD37FD007E18820CAE658E3C1F8A60D5D3B79ED9DD5FDD9"


def require_arelle_version() -> str:
    """Abort unless the installed Arelle is exactly the pinned version."""
    from arelle import Version
    v = getattr(Version, "version", None)
    if v != ARELLE_VERSION:
        raise RuntimeError(
            f"pinned Arelle {ARELLE_VERSION} required, found {v!r} — "
            "re-validate the corpus before parsing")
    return v


class _LinearBase64:
    """O(n) equivalent of lexicalPatterns['base64Binary'] (callers only test
    truthiness). Faithful to the original regex-module (V0) semantics, which
    were mapped empirically: each base64 char may be followed by AT MOST ONE
    whitespace; whitespace is internal only - the last meaningful char must be
    a base64 char or '='; a single trailing '\\n' is tolerated by the '$'
    anchor (it matches before a final newline without consuming it); padding
    '=' is confined to the final quad with the pad-adjacent character
    restricted so unused bits are zero."""
    def match(self, value):
        if value.endswith("\n"):
            value = value[:-1]            # '$' permits one final '\n'
        n = len(value)
        if n == 0:
            return True
        if value[n - 1] in _WSSET:
            return None                   # no other trailing whitespace
        i, cnt, last = 0, 0, None
        while i < n:
            ch = value[i]
            if ch in _B64SET:
                last = ch
                cnt += 1
                i += 1
                if i < n and value[i] in _WSSET:
                    i += 1
            else:
                break
        if i == n:
            return True if cnt % 4 == 0 else None
        if value[i] != "=":
            return None
        t = cnt % 4
        if t == 3:                        # tail: B B R1 '='
            if last not in _B64_R1:
                return None
            return True if i + 1 == n else None
        if t == 2:                        # tail: B R2 '=' \s? '='
            if last not in _B64_R2:
                return None
            i += 1
            if i < n and value[i] in _WSSET:
                i += 1
            return True if i < n and value[i] == "=" and i + 1 == n else None
        return None


def _shim_selftest(orig) -> dict:
    """Equivalence vs the ORIGINAL Arelle pattern object (regex module, V0
    semantics) on curated + deterministic fuzz inputs, plus a large payload
    that must complete in linear time. Raises on any divergence."""
    shim = _LinearBase64()
    cases = ["", "QUJD", "QQ==", "QUE=", "QUJD\nRUZH IEla", "QUJD RA==\t",
             "QUJ=", "QQ=Q", "QUJDRA==", "QUJDQQ", "QUJ D", "====", "A===",
             "TWFuTWFu", "QUJD-EFH", "QQ= =", "QUE =", "QU  JD", " Q",
             "AB==", "ABC =", "QUJD= ", "QUJD ", "QUJD\n", "QUJD\n\n",
             "QUJD \n", "QUJ D ", "QUE= ", "QUE=\n", "QQ== ", "QQ==\n",
             "QUJD QUJD", "QUJD  QUJD", "QQ = =", "Q Q==", "QUJD\nQUJD",
             "\n", " ", "QUJD\r\n", "QUE=\n\n"]
    for c in cases:
        want = orig.match(c) is not None
        got = shim.match(c) is not None
        if want != got:
            raise RuntimeError(f"shim divergence on {c!r}: orig={want} shim={got}")
    import random
    rng = random.Random(20260916)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/= \t\n\r-"
    fuzz = 0
    for _ in range(4000):
        c = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 40)))
        want = orig.match(c) is not None
        got = shim.match(c) is not None
        if want != got:
            raise RuntimeError(f"shim divergence on fuzz {c!r}: orig={want} shim={got}")
        fuzz += 1
    big = base64.b64encode(b"\xab" * (9 * 1024 * 1024)).decode("ascii")
    t0 = time.time()
    if shim.match(big) is not True:
        raise RuntimeError("shim rejected a valid large base64 payload")
    if time.time() - t0 > 5:
        raise RuntimeError("shim is not linear-time on a 12 MB payload")
    return {"cases": len(cases), "fuzz_cases": fuzz, "large_payload_bytes": len(big)}


_SHIM_STATE: dict | None = None


def install_base64_lexical_shim() -> dict:
    """Install the base64Binary lexical shim — fail-closed.

    Applies ONLY to arelle-release 2.44.0 and ONLY while the original regex
    is byte-identical to the fingerprint recorded at gate time. If Arelle
    changes the code, this fails loudly instead of patching silently over an
    unreviewed upstream change. Idempotent within a process.
    """
    global _SHIM_STATE
    if _SHIM_STATE is not None:
        return _SHIM_STATE
    require_arelle_version()
    import arelle.XmlValidate as _XV
    orig = _XV.lexicalPatterns.get("base64Binary")
    fp = hashlib.sha256(getattr(orig, "pattern", "").encode("utf-8")).hexdigest().upper()
    if fp != _ORIG_B64_PATTERN_SHA256:
        raise RuntimeError(
            f"lexicalPatterns['base64Binary'] fingerprint {fp} != expected "
            f"{_ORIG_B64_PATTERN_SHA256} - upstream changed, shim NOT applied")
    selftest = _shim_selftest(orig)
    _XV.lexicalPatterns["base64Binary"] = _LinearBase64()
    _SHIM_STATE = {
        "type": "base64Binary",
        "arelle_version_gated": ARELLE_VERSION,
        "orig_pattern_sha256": _ORIG_B64_PATTERN_SHA256,
        "shim_source_sha256": hashlib.sha256(
            inspect.getsource(_LinearBase64).encode("utf-8")).hexdigest().upper(),
        "selftest": selftest,
    }
    return _SHIM_STATE


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def prepare_xbrl_entrypoint(src: Path, workdir: Path, name: str) -> Path:
    """SHA-verified ``.xbrl`` copy for raw artefacts stored as ``.zip``.

    The preserved artefact is never modified; Arelle receives an identical-
    bytes copy whose suffix it will parse as an XML instance.
    """
    entry = workdir / f"{name}.xbrl"
    shutil.copyfile(src, entry)
    if sha256_file(entry) != sha256_file(src):
        raise RuntimeError(f"entrypoint copy diverged from raw artefact: {src}")
    return entry


@dataclass
class ParseSpec:
    """Everything an offline Arelle session needs for one filing."""
    entrypoint: str                       # report package .zip or .xbrl
    taxonomy_packages: list[str] = field(default_factory=list)
    disclosure_system: str | None = None  # e.g. "esef-2022" / "esef-2024"
    plugins: str = "saveLoadableOIM"
    validate: bool = True
    oim_path: str | None = None
    lexical_shim: bool = False            # install base64 shim (IPP payloads)


class ParseSession:
    """One Arelle Session per filing — context manager holding the model.

    The model stays alive only inside the ``with`` block (keepOpen); the
    caller must extract all facts/metadata before exit.
    """

    def __init__(self, spec: ParseSpec):
        self.spec = spec
        self.log_msgs: list[dict] = []
        self.model = None
        self.run_ok = False
        self._session = None

    def __enter__(self) -> "ParseSession":
        require_arelle_version()
        shim_info = install_base64_lexical_shim() if self.spec.lexical_shim else None
        self.shim_info = shim_info
        from arelle.RuntimeOptions import RuntimeOptions
        from arelle.api.Session import Session
        opts = RuntimeOptions(
            entrypointFile=self.spec.entrypoint,
            internetConnectivity="offline",
            packages=list(self.spec.taxonomy_packages),
            plugins=self.spec.plugins,
            validate=self.spec.validate,
            keepOpen=True,
            pluginOptions=(
                {"saveLoadableOIM": self.spec.oim_path}
                if self.spec.oim_path else None),
            logLevel="WARNING",
            **({"disclosureSystemName": self.spec.disclosure_system}
               if self.spec.disclosure_system else {}),
        )

        class _H(logging.Handler):
            def emit(hself, record):
                self.log_msgs.append({
                    "level": record.levelname,
                    "code": getattr(record, "messageCode", ""),
                    "message": record.getMessage()[:500],
                })

        self._session = Session()
        self.run_ok = self._session.run(opts, logHandler=_H())
        models = self._session.get_models()
        self.model = models[0] if models else None
        return self

    def __exit__(self, *exc):
        if self._session is not None:
            self._session.close()
        return False
