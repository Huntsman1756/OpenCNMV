"""Capture orchestration: live CNMV -> preserved evidence + observation.

This is the public ``opencnmv observe`` engine — the only production
code path that touches the network. ``update --evidence-dir`` reuses
``assemble_observation`` offline over an existing evidence dir.
"""
from __future__ import annotations

from pathlib import Path

from opencnmv.capture import discover
from opencnmv.capture.assemble import assemble_observation
from opencnmv.capture.contract import (ISSUERS, MIN_DELAY_S, SEARCH_FROM,
                                       SEARCH_TO, USER_AGENT,
                                       CaptureError,
                                       load_issuer_registry)
from opencnmv.capture.fetch import (EvidenceStore, PoliteSession,
                                    load_latest_manifest)
from opencnmv.serialize import write_canonical


def resolve_scope(issuer_nifs: list[str] | None,
                  families: list[str] | None,
                  registry: dict | None = None) -> tuple[list[str],
                                                         set[str]]:
    """Scope validation — fail closed on issuers outside the active
    registry (the frozen corpus unless ``--issuer-registry`` was given).
    """
    reg = ISSUERS if registry is None else registry
    nifs = list(issuer_nifs) if issuer_nifs else list(reg)
    unknown = [n for n in nifs if n not in reg]
    if unknown:
        where = ("frozen corpus" if registry is None
                 else "issuer-registry file")
        raise CaptureError(
            f"issuers outside the {where}: {unknown} "
            f"(allowed: {sorted(reg)})")
    fams = set(families) if families else {"ifa", "ipp"}
    bad = fams - {"ifa", "ipp"}
    if bad:
        raise CaptureError(f"unknown families: {sorted(bad)} "
                           "(allowed: ifa, ipp)")
    return nifs, fams


def observe(*, evidence_dir: Path, out: Path | None,
            issuer_nifs: list[str] | None = None,
            families: list[str] | None = None,
            desde: str = SEARCH_FROM, hasta: str = SEARCH_TO,
            min_delay: float = MIN_DELAY_S,
            dataset_dir: Path | None = None,
            tax_dir: Path | None = None,
            issuer_registry: Path | None = None,
            session=None) -> dict:
    """Run one controlled capture. Returns a result summary dict.

    Writes the capture manifest under ``<evidence_dir>/runs/<id>/`` and,
    when ``out`` is given, the assembled CANONICAL_OBSERVATION_V1
    document (assembled against ``dataset_dir`` tables when provided,
    else as a full bootstrap projection).

    ``issuer_registry`` selects an ISSUER_REGISTRY_V1 file as the active
    issuer set; absent it, the frozen corpus applies.
    """
    registry = (load_issuer_registry(issuer_registry)
                if issuer_registry else None)
    nifs, fams = resolve_scope(issuer_nifs, families, registry)
    store = EvidenceStore(Path(evidence_dir))
    sess = session or PoliteSession(min_delay=min_delay,
                                    user_agent=USER_AGENT)
    manifest = discover.run_discovery(sess, store, nifs, fams,
                                      desde, hasta, registry=registry)
    manifest_path = store.finish_run(manifest)

    obs = None
    if out is not None:
        tables = None
        if dataset_dir is not None:
            from opencnmv.update.apply import load_tables
            tables = load_tables(dataset_dir)
        obs = assemble_observation(manifest, tables=tables,
                                   evidence_root=Path(evidence_dir),
                                   tax_dir=tax_dir)
        write_canonical(obs, Path(out))

    return {"capture_id": manifest["capture_id"],
            "manifest": str(manifest_path),
            "observation": str(out) if out else None,
            "observation_sha256": (obs or {}).get("observation_sha256"),
            "filings": len(obs["filings"]) if obs else None,
            "warnings": manifest["warnings"],
            "fetches": len(manifest["fetch_log"])}


def assemble_from_evidence(evidence_dir: Path, *,
                           dataset_dir: Path | None = None,
                           tax_dir: Path | None = None,
                           run: str | None = None,
                           work_dir: Path | None = None) -> dict:
    """Offline leg of ``update --evidence-dir``: assemble the observation
    from a preserved capture run — no network access."""
    manifest, mp = load_latest_manifest(Path(evidence_dir), run)
    tables = None
    if dataset_dir is not None:
        from opencnmv.update.apply import load_tables
        tables = load_tables(dataset_dir)
    obs = assemble_observation(manifest, tables=tables,
                               evidence_root=Path(evidence_dir),
                               tax_dir=tax_dir, work_dir=work_dir)
    return obs
