"""Thin adapter over Arelle 2.44.0 — the authoritative XBRL parser.

OpenCNMV does not implement XBRL semantics; this module only configures an
offline Arelle session over a preserved ESEF report package and yields
normalized fact records for the canonical layer. Taxonomy resolution comes
from caller-pinned taxonomy packages, never the network or the Arelle
user-level web cache.
"""
from __future__ import annotations

import hashlib, os
from pathlib import Path

ARELLE_VERSION = "2.44.0"


def iter_facts(package_path: str | Path,
               taxonomy_packages: list[str | Path],
               cache_dir: str | Path):
    """Load an ESEF report package fully offline and yield fact dicts.

    package_path: preserved report-package ZIP bytes on disk.
    taxonomy_packages: locally-pinned ESMA/IFRS/LEI taxonomy packages.
    cache_dir: per-run Arelle cache (must be empty/fresh — determinism).
    """
    os.environ.setdefault("ARELLE_ARGS", "")
    from arelle import Cntlr, ModelXbrl  # noqa: delayed import

    cntlr = Cntlr.Cntlr(logFileName="logToStdOut",
                        disablePersistentConfig=True)
    try:
        cntlr.webCache.workOffline = True
        cntlr.webCache.cacheDir = str(cache_dir)
        options = type("O", (), {})()
        options.internetConnectivity = "offline"
        options.validate = False
        options.packages = [str(p) for p in taxonomy_packages]
        mx = ModelXbrl.load(cntlr, str(package_path),
                            modelXbrlLoadOptions=options)
        for f in mx.facts:
            q = f.qname
            ctx = f.context
            dims = {}
            if ctx is not None:
                for dim, mem in (ctx.qnameDims or {}).items():
                    dims[f"{dim.namespaceURI}#{dim.localName}"] = (
                        f"E:{mem.memberQname.namespaceURI}#"
                        f"{mem.memberQname.localName}"
                        if mem.isExplicit else f"T:{mem.typedMember.xValue}")
            yield {
                "concept": f"{q.namespaceURI}#{q.localName}",
                "concept_type": (f"{f.concept.type.qname.namespaceURI}#"
                                 f"{f.concept.type.qname.localName}"
                                 if f.concept is not None
                                 and f.concept.type is not None else None),
                "entity": (f"{ctx.entityIdentifier[0]}|"
                           f"{ctx.entityIdentifier[1]}"
                           if ctx is not None else None),
                "period": (ctx.instantDatetime.strftime("%Y-%m-%d")
                           if ctx is not None and ctx.isInstantPeriod
                           else (f"{ctx.startDatetime:%Y-%m-%d}/"
                                 f"{ctx.endDatetime:%Y-%m-%d}"
                                 if ctx is not None else None)),
                "dimensions": dims,
                "unit": (next(iter(f.unit.measures[0])).namespaceURI + "#" +
                         next(iter(f.unit.measures[0])).localName
                         if getattr(f, "unit", None) is not None else None),
                "decimals": getattr(f, "decimals", None),
                "isNil": f.isNil,
                "lang": getattr(f, "xmlLang", None),
                "value": f.value,
                "value_sha256": hashlib.sha256(
                    (f.value or "").encode("utf-8")).hexdigest()}
    finally:
        cntlr.close()
