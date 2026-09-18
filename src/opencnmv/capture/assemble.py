"""Evidence -> CANONICAL_OBSERVATION_V1 assembly.

``assemble_observation`` takes one capture manifest (the structured
record of a live discovery run) plus the base dataset's table rows and
produces the observation document the update engine consumes.

Assembly is a *rebase onto recorded history*:

  * Filings already in the dataset keep every recorded row verbatim —
    historical capture records are never re-derived.
  * Live capture contributes *change signals*: resolved package hashes,
    view resolutions, infadicionifa event rows, IPP artifact hashes.
    Identical signals leave the filing untouched (NO_CHANGE); a changed
    signal produces a new variant_version / event / artifact row —
    never an in-place edit.
  * Filings absent from the dataset are constructed entirely from the
    live evidence (NEW_FILING).
  * Fact states are parsed only for variant_versions the observation
    introduces (per the observation contract); parsing needs the pinned
    taxonomy dir and is skipped entirely when nothing changed.
"""
from __future__ import annotations

import copy
import io
import json
import re
from pathlib import Path

from opencnmv.canonicalize import events as xevents
from opencnmv.canonicalize import extension_mapping as xmap
from opencnmv.canonicalize import filing as xfiling
from opencnmv.canonicalize import variants as xvariants
from opencnmv.capture.contract import ISSUERS, CaptureError
from opencnmv.capture.parse import map_variants, parse_state
from opencnmv.dataset import tables as dtables
from opencnmv.model import ids
from opencnmv.provenance.hashes import artifact_set_id
from opencnmv.source.cnmv.discovery import nreg_from_infadicion
from opencnmv.update import classify as classify_mod
from opencnmv.update import observe as uobs

ESEF_PKG_ROLE = "ESEF_PACKAGE_ZIP_XBRL"
IPP_ROLE = "IPP_XBRL"

_EVENT_TYPE_RULES = (
    (re.compile(r"sustitu", re.I), "SUBSTITUTION"),
    (re.compile(r"etiquetado|fichero", re.I), "FILE_TAGGING_CORRECTION"),
    (re.compile(r"requerim", re.I), "CNMV_REQUIREMENT_RESPONSE"),
    (re.compile(r"certificad", re.I), "CERTIFICATE"),
)
_FORMULACION_RE = re.compile(r"formulaci", re.I)
_DATE_CELL_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _iso(dmy: str | None) -> str | None:
    m = _DATE_CELL_RE.match(dmy or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _event_type(label: str) -> str:
    for rx, t in _EVENT_TYPE_RULES:
        if rx.search(label):
            return t
    return "OTHER"


def _event_label(cells: list[str]) -> str:
    """Longest non-date cell = the event's UI label (evidence, never
    authority — scope comes from the preserved document)."""
    return max((c for c in cells if not _DATE_CELL_RE.match(c)),
               key=len, default="")


def _fy_of(period_end: str) -> str:
    m = re.search(r"(\d{4})$", period_end or "")
    return f"FY{m.group(1)}" if m else ""


class _Ctx:
    """Per-assembly context: base tables + evidence root + taxonomy +
    issuer identities carried by the capture manifest."""

    def __init__(self, tables, evidence_root: Path,
                 tax_dir: Path | None, work_dir: Path,
                 issuer_map: dict | None = None):
        self.tables = tables
        self.root = Path(evidence_root)
        self.tax_dir = Path(tax_dir) if tax_dir else None
        self.work = Path(work_dir)
        self.issuers = issuer_map or {}
        self.warnings: list[str] = []
        self.unresolved: list[dict] = []


# ---- base reconstruction ---------------------------------------------------

def _base_filing(ctx: _Ctx, filing_id: str) -> dict | None:
    """Reconstruct {fx, extras, extra_artifacts} from base rows."""
    if not ctx.tables:
        return None
    rows = classify_mod.filing_scoped_rows(ctx.tables, filing_id)
    if not rows["filing"]:
        return None
    fx = dtables.filing_from_rows(
        rows["filing"][0], rows["filing_version"],
        rows["submission_variant"], rows["variant_version"],
        rows["view_resolution"], rows["version_event"],
        rows["event_affects"], rows["artifact"],
        rows["extension_mapping"])
    extras = (json.loads(rows["filing"][0]["extras_json"])
              if rows["filing"][0].get("extras_json") else None)
    extra_artifacts = [
        {"event_id": a["owner_id"],
         "artifact": dtables._artifact_dict(a)}
        for a in rows["artifact"] if a["owner_kind"] == "version_event"]
    return {"fx": fx, "extras": extras,
            "extra_artifacts": extra_artifacts}


def _base_extension_mapping_files(ctx: _Ctx, filing_id: str
                                  ) -> list[dict]:
    """Existing extension_mapping rows -> extension_mapping_files records
    (record_json preserves each raw G1-C-style record verbatim)."""
    if not ctx.tables:
        return []
    rows = [r for r in ctx.tables.get("extension_mapping", [])
            if r["filing_id"] == filing_id]
    files: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r["source_file"],
                                         r["source_ordinal"])):
        f = files.setdefault(r["source_file"], {
            "source_file": r["source_file"],
            "source_lang": r["source_variant_id"].rsplit("#", 1)[-1],
            "target_lang": (r["target_variant_id"].rsplit("#", 1)[-1]
                            if r.get("target_variant_id") else "en"),
            "records": []})
        f["records"].append(json.loads(r["record_json"]))
    return list(files.values())


# ---- state parsing ---------------------------------------------------------

def _state_for(ctx: _Ctx, artifact_rec: dict, *, kind: str,
               fy: str | None, state_id: str) -> tuple[dict, dict]:
    """Parse one new variant_version's artifact. Returns
    (observation state, raw parse result)."""
    if ctx.tax_dir is None:
        raise CaptureError(
            f"{state_id}: new/changed content requires --taxonomy-dir "
            f"(pinned taxonomy packages) to parse")
    path = ctx.root / artifact_rec["evidence_path"]
    res = parse_state(path, kind=kind, fy=fy, tax_dir=ctx.tax_dir,
                      work_dir=ctx.work, name=state_id)
    prov = {"state_id": state_id,
            "artifact_id": ids.artifact_id(artifact_rec["sha256"]),
            "role": ESEF_PKG_ROLE if kind == "esef" else IPP_ROLE,
            "sha256": artifact_rec["sha256"],
            "byte_size": artifact_rec["byte_size"],
            "media_type": artifact_rec["media_type"],
            "source_url": artifact_rec.get("source_url"),
            "resolved_url": artifact_rec.get("source_url"),
            "retrieved_at": artifact_rec.get("retrieved_at"),
            "http_status": artifact_rec.get("http_status"),
            "evidence_path": artifact_rec["evidence_path"],
            "arelle_version": res["arelle_version"],
            "lexical_shim": res["lexical_shim"]}
    st = {"state_id": state_id, "variant_version_id": None,
          "profile": kind, "facts": res["facts"],
          "units": res["units"], "provenance": prov}
    return st, res


def _maybe_state(ctx: _Ctx, artifact_rec: dict, *, kind: str,
                 fy: str | None, state_id: str,
                 on_fail) -> tuple[dict, dict] | None:
    """``_state_for`` with classified failure semantics.

    A missing ``--taxonomy-dir`` is an *operator* error — parsing was
    requested without the pinned taxonomy input, so it still raises
    fail-closed. A parse failure on present inputs is a *source*
    anomaly: the variant stays observed (its artifact is real preserved
    evidence) but yields no facts; ``on_fail`` produces the outcome.
    """
    if ctx.tax_dir is None:
        return _state_for(ctx, artifact_rec, kind=kind, fy=fy,
                          state_id=state_id)
    try:
        return _state_for(ctx, artifact_rec, kind=kind, fy=fy,
                          state_id=state_id)
    except CaptureError as ex:
        ctx.unresolved.append(on_fail(ex))
        return None


def _parse_existing(ctx: _Ctx, sha256: str, *, kind: str,
                    fy: str | None, name: str) -> dict:
    """Re-parse an unchanged variant's preserved package (for mapping
    recomputation) — bytes come from the evidence store by sha."""
    if ctx.tax_dir is None:
        raise CaptureError(
            f"{name}: mapping recomputation requires --taxonomy-dir")
    cand = sorted(ctx.root.glob(f"artifacts/{sha256}.*"))
    if not cand:
        raise CaptureError(
            f"{name}: package {sha256[:12]}… not in evidence dir — "
            f"cannot recompute mapping")
    return parse_state(cand[0], kind=kind, fy=fy, tax_dir=ctx.tax_dir,
                       work_dir=ctx.work, name=name)


# ---- ESEF ------------------------------------------------------------------

def _cert_text(body: bytes) -> str | None:
    """PDF text for scope classification. Missing pypdf means the reason
    clause is unobservable -> VARIANT_SCOPE_NOT_OBSERVABLE (fail closed)."""
    if body[:4] != b"%PDF":
        return None
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        rd = PdfReader(io.BytesIO(body))
        return "\n".join((p.extract_text() or "") for p in rd.pages)
    except Exception:
        return None


def _event_artifact(doc: dict) -> dict:
    return {"artifact_id": doc["artifact_id"], "role": "EVENT_DOCUMENT",
            "sha256": doc["sha256"], "bytes": doc["byte_size"],
            "media_type": doc["media_type"],
            "source_url": doc.get("source_url"),
            "package_lang_tag": None}


def _build_esef_events(fid: str, view_es: dict, walk: dict | None,
                       ctx: _Ctx, extra_artifacts: list[dict]
                       ) -> list[dict]:
    """formulacion + infadicionifa events, merged over recorded history.

    Events are emitted with live-derived content: identical to the
    recorded row -> unchanged; drift under the same event_id ->
    SOURCE_STATE_CONFLICT (fail closed, never masked).
    """
    cells = view_es["registry_row"]["cells"]
    links = view_es["registry_row"].get("infadicion") or []
    nreg = nreg_from_infadicion(links[0])[0] if links else None

    events = [xevents.event(
        fid, "formulacion", "CERTIFICATE",
        event_date=cells[2] if len(cells) > 2 else None,
        source_label="formulación y firma", source_nreg=nreg,
        scope_status="NOT_A_VERSION_TRANSITION")]
    formulacion_date = cells[2] if len(cells) > 2 else None

    dated_keys: dict[str, int] = {}
    for row in (walk or {}).get("events", []):
        date_dmy = next((c for c in row["cells"]
                         if _DATE_CELL_RE.match(c)), None)
        label = _event_label(row["cells"])
        if not label and not row.get("tokens"):
            continue      # period-declaration row, not an event
        if (_iso(date_dmy) == _iso(formulacion_date)
                and _FORMULACION_RE.search(label)):
            continue                      # same event as formulacion
        key_base = _iso(date_dmy) or "unknown"
        n = dated_keys.get(key_base, 0)
        dated_keys[key_base] = n + 1
        key = key_base if n == 0 else f"{key_base}.{n}"
        doc = row["doc_artifacts"][0] if row["doc_artifacts"] else None
        ev_art = None
        reason = None
        eid = ids.event_id(fid, key)
        if doc is not None:
            body = (ctx.root / doc["evidence_path"]).read_bytes()
            reason = xevents.reason_clause(_cert_text(body) or "")
            if not any(ea["event_id"] == eid and
                       ea["artifact"]["sha256"] == doc["sha256"]
                       for ea in extra_artifacts):
                extra_artifacts.append(
                    {"event_id": eid, "artifact": _event_artifact(doc)})
            ev_art = doc["artifact_id"]
        scope, _basis = xevents.classify_scope(reason)
        events.append(xevents.event(
            fid, key, _event_type(label), event_date=_iso(date_dmy),
            source_label=label or None, source_nreg=None,
            evidence_artifact_id=ev_art, scope_status=scope,
            affects=[xevents.affects(
                component_scope="NOT_IDENTIFIED",
                component_description=reason,
                scope_basis=ev_art)]))
    return events


def _issuer_map(manifest: dict) -> dict:
    """issuer_key -> {key, nif, denomination, lei} for assembly.

    Identity comes from the capture manifest's scope entries (carried by
    ``run_discovery``); manifests captured before that field existed fall
    back to the frozen registry by nif, and the registry itself is the
    last resort for manifests without scope entries at all.
    """
    out: dict[str, dict] = {}
    for nif, e in ISSUERS.items():
        out[e["key"]] = {"key": e["key"], "nif": nif,
                         "denomination": e["denomination"],
                         "lei": e["lei"]}
    for e in manifest.get("scope", {}).get("issuers", []):
        ent = out.get(e["key"], {"key": e["key"]})
        ent["nif"] = e["nif"]
        if e.get("denomination") is not None:
            ent["denomination"] = e["denomination"]
        if e.get("lei") is not None:
            ent["lei"] = e["lei"]
        out[e["key"]] = ent
    return out


def _issuer_dict(ctx: _Ctx, issuer_key: str, *,
                 with_nif: bool = False) -> dict:
    e = ctx.issuers.get(issuer_key)
    if e is None or not e.get("denomination") or not e.get("lei"):
        raise CaptureError(
            f"issuer identity unresolved for key {issuer_key!r} — "
            "not in manifest scope or frozen registry")
    iss = {"denomination": e["denomination"], "lei": e["lei"]}
    if with_nif:
        iss["nif"] = e["nif"]
    return iss


def assemble_esef(registro: str, views: dict[str, dict],
                  walk: dict | None, issuer_key: str, base: dict | None,
                  ctx: _Ctx) -> dict:
    """One ESEF filing observation entry (rebase onto recorded history)."""
    fid = ids.filing_id(registro, ids.IFA)
    view_es = views.get("es")
    if view_es is None or view_es.get("status") is not None \
            or not view_es.get("package"):
        raise CaptureError(f"{fid}: no usable es view captured — "
                           f"cannot anchor registry identity")
    fx_base = copy.deepcopy(base["fx"]) if base else None
    extra_artifacts = list(base["extra_artifacts"]) if base else []

    events = _build_esef_events(fid, view_es, walk, ctx, extra_artifacts)
    links = view_es["registry_row"].get("infadicion") or []
    nreg = nreg_from_infadicion(links[0])[0] if links else None
    period_end = view_es["registry_row"]["cells"][1]
    fy = _fy_of(period_end)

    if fx_base is None:
        fx = xfiling.new_filing(registro, _issuer_dict(ctx, issuer_key),
                                period_end=period_end)
        fx["filing_versions"] = [xfiling.filing_version(
            fid, nreg, submission_kind="ORIGINAL_SUBMISSION")]
    else:
        fx = fx_base
        # live-derived fields overwrite so the classifier sees drift
        fx["period_end"] = period_end

    fx["version_events"] = events
    fx["view_resolutions"] = [
        xvariants.view_resolution(
            fid, lang, views[lang]["resolved_submission_language"],
            views[lang]["resolution_mode"])
        for lang in ("es", "en") if lang in views]

    states: list[dict] = []
    parse_res: dict[str, dict] = {}       # variant_version_id -> parse res
    new_version = False
    base_variants = {sv["variant_id"]: sv
                     for sv in (fx_base or {}).get("submission_variants",
                                                  [])}
    out_variants: list[dict] = []
    for lang in ("es", "en"):
        v = views.get(lang)
        if v is None or v["resolution_mode"] != "SUBMITTED_VARIANT":
            continue
        vid = ids.variant_id(fid, lang)
        pkg = v["package"]
        art = xfiling.artifact(
            ESEF_PKG_ROLE, pkg["sha256"], bytes_=pkg["byte_size"],
            media_type=pkg["media_type"],
            source_url=pkg.get("source_url"), package_lang_tag=lang)
        aset = artifact_set_id([{"role": ESEF_PKG_ROLE,
                                 "sha256": pkg["sha256"]}])
        sv_base = base_variants.get(vid)
        if sv_base is not None:
            sv = copy.deepcopy(sv_base)
            latest = sv["variant_versions"][-1]
            if latest["artifact_set_id"] == aset:
                out_variants.append(sv)
                continue
            n = len(sv["variant_versions"]) + 1
            vv = xvariants.variant_version(
                vid, n, observed=True, artifact_set_id=aset,
                artifacts=[art],
                supersedes=latest["variant_version_id"])
            sv["variant_versions"].append(vv)
            out_variants.append(sv)
            sid = f"{issuer_key}-{fy}-{lang}-v{n}"
        else:
            sv = xvariants.variant(fid, lang)
            vv = xvariants.variant_version(
                vid, 1, observed=True, artifact_set_id=aset,
                artifacts=[art],
                created_by_event_id=ids.event_id(fid, "formulacion"))
            sv["variant_versions"].append(vv)
            out_variants.append(sv)
            sid = f"{issuer_key}-{fy}-{lang}"
            n = 1
        new_version = True
        got = _maybe_state(ctx, pkg, kind="esef", fy=fy, state_id=sid,
                           on_fail=lambda ex: {
                               "scope": "variant", "family": "ESEF_IFA",
                               "issuer_key": issuer_key,
                               "filing_id": fid, "view": lang,
                               "variant_version_id":
                                   vv["variant_version_id"],
                               "reason": "PARSE_FAILED",
                               "detail": str(ex),
                               "artifacts": [pkg["sha256"]]})
        if got is None:
            continue
        st, res = got
        st["variant_version_id"] = vv["variant_version_id"]
        states.append(st)
        parse_res[vv["variant_version_id"]] = res
    for vid, sv in base_variants.items():
        if vid not in {s["variant_id"] for s in out_variants}:
            out_variants.append(copy.deepcopy(sv))
            ctx.warnings.append(
                f"{fid}: variant {vid} not submitted in live views; "
                f"recorded rows kept")
    fx["submission_variants"] = out_variants

    # substitution events with a known nreg mint a filing_version
    known_fv = {fv["filing_version_id"] for fv in fx["filing_versions"]}
    for ev in events:
        if ev["event_type"] == "SUBSTITUTION" and ev.get("source_nreg"):
            fv = xfiling.filing_version(fid, ev["source_nreg"],
                                        ev.get("event_date"),
                                        "SUBSTITUTION")
            if fv["filing_version_id"] not in known_fv:
                fx["filing_versions"].append(fv)
                known_fv.add(fv["filing_version_id"])

    submitted = [sv for sv in out_variants
                 if any(v["observed"] for v in sv["variant_versions"])]
    if base is not None and not new_version:
        fx["extension_mappings"] = (fx_base or {}).get(
            "extension_mappings", [])
        ext_files = _base_extension_mapping_files(ctx, fid)
    elif len(submitted) == 2 and {s["submission_language"]
                                  for s in submitted} == {"es", "en"}:
        try:
            records = _compute_extmap(fid, submitted, states, parse_res,
                                      issuer_key, fy, ctx)
        except CaptureError as ex:
            ctx.unresolved.append(
                {"scope": "mapping", "family": "ESEF_IFA",
                 "issuer_key": issuer_key, "filing_id": fid,
                 "reason": "EXTMAP_FAILED", "detail": str(ex),
                 "artifacts": []})
            records = []
        fx["extension_mappings"] = [
            xmap.mapping_record(fid, "es", "en", r)
            for r in records if r.get("pair_id")]
        ext_files = ([{"source_file": f"{issuer_key}-{fy}",
                       "source_lang": "es", "target_lang": "en",
                       "records": records}] if records else [])
    else:
        fx["extension_mappings"] = (fx_base.get("extension_mappings", [])
                                    if fx_base else [])
        ext_files = (_base_extension_mapping_files(ctx, fid)
                     if base is not None else [])

    return {"filing": fx, "extras": base["extras"] if base else None,
            "extra_artifacts": extra_artifacts,
            "extension_mapping_files": ext_files,
            "states": states}


def _compute_extmap(fid, submitted, states, parse_res, issuer_key, fy,
                    ctx: _Ctx) -> list[dict]:
    """G1-C pairing for a dual filing whose content changed or is new."""
    per_lang: dict[str, dict] = {}
    for sv in submitted:
        lang = sv["submission_language"]
        vv = sv["variant_versions"][-1]
        res = parse_res.get(vv["variant_version_id"])
        if res is None:
            art = vv["artifacts"][0]
            res = _parse_existing(ctx, art["sha256"], kind="esef",
                                  fy=fy,
                                  name=f"{issuer_key}-{fy}-{lang}")
        per_lang[lang] = res
    return map_variants(fid, per_lang["es"]["structure"],
                        per_lang["en"]["structure"],
                        per_lang["es"]["facts"], per_lang["en"]["facts"])


# ---- IPP -------------------------------------------------------------------

def assemble_ipp(rec: dict, base: dict | None, ctx: _Ctx) -> dict | None:
    """One IPP slot observation entry; None when the slot is unlisted."""
    if rec.get("status") != "CAPTURED":
        return None
    issuer_key, nreg = rec["issuer_key"], rec["nreg"]
    fid = ids.filing_id(nreg, ids.IPP)
    art = rec["artifact"]
    fx_base = copy.deepcopy(base["fx"]) if base else None
    extra_artifacts = list(base["extra_artifacts"]) if base else []
    filed_at = _iso(rec.get("published"))

    ipp_artifact = xfiling.artifact(
        IPP_ROLE, art["sha256"], bytes_=art["byte_size"],
        media_type=art["media_type"], source_url=art.get("source_url"),
        package_lang_tag="es")
    aset = artifact_set_id([{"role": IPP_ROLE, "sha256": art["sha256"]}])
    sid = f"{issuer_key}-{rec['slot']}"

    states: list[dict] = []
    if fx_base is None:
        fx = xfiling.new_filing(nreg, _issuer_dict(ctx, issuer_key,
                                                 with_nif=True),
                                period_end=rec["period_end"],
                                family="IPP")
        fx["filing_id"] = fid
        fx["filing_versions"] = [dict(
            xfiling.filing_version(fid, nreg, filed_at,
                                   "ORIGINAL_SUBMISSION"),
            artifacts=[ipp_artifact])]
        vid = ids.variant_id(fid, "es")
        sv = xvariants.variant(fid, "es")
        sv["variant_versions"].append(xvariants.variant_version(
            vid, 1, observed=True, artifact_set_id=aset, artifacts=[]))
        fx["submission_variants"] = [sv]
        fx["view_resolutions"] = [xvariants.view_resolution(
            fid, "es", "es", "SUBMITTED_VARIANT")]
        got = _maybe_state(ctx, art, kind="ipp", fy=None, state_id=sid,
                           on_fail=lambda ex: {
                               "scope": "variant", "family": "IPP",
                               "issuer_key": issuer_key,
                               "filing_id": fid,
                               "variant_version_id":
                                   ids.variant_version_id(vid, 1),
                               "reason": "PARSE_FAILED",
                               "detail": str(ex),
                               "artifacts": [art["sha256"]]})
        if got is not None:
            st = got[0]
            st["variant_version_id"] = ids.variant_version_id(vid, 1)
            states.append(st)
        return {"filing": fx, "extras": None,
                "extra_artifacts": extra_artifacts,
                "extension_mapping_files": [], "states": states}

    fx = fx_base
    fx["period_end"] = rec["period_end"]
    vid = ids.variant_id(fid, "es")
    sv_live: dict | None = None
    for s in fx["submission_variants"]:
        if s["variant_id"] == vid:
            sv_live = s
            break
    if sv_live is None:
        raise CaptureError(f"{fid}: recorded filing has no es variant")
    latest = sv_live["variant_versions"][-1]
    ext_files = _base_extension_mapping_files(ctx, fid)
    if latest["artifact_set_id"] == aset:
        return {"filing": fx, "extras": base["extras"] if base else None,
                "extra_artifacts": extra_artifacts,
                "extension_mapping_files": ext_files, "states": []}
    # changed artifact under the same nreg -> append-only new version
    fx["filing_versions"][0].setdefault("artifacts", []).append(
        ipp_artifact)
    vv = xvariants.variant_version(
        vid, len(sv_live["variant_versions"]) + 1, observed=True,
        artifact_set_id=aset, artifacts=[],
        supersedes=latest["variant_version_id"])
    sv_live["variant_versions"].append(vv)
    got = _maybe_state(
        ctx, art, kind="ipp", fy=None,
        state_id=f"{sid}-v{len(sv_live['variant_versions'])}",
        on_fail=lambda ex: {
            "scope": "variant", "family": "IPP",
            "issuer_key": issuer_key, "filing_id": fid,
            "variant_version_id": vv["variant_version_id"],
            "reason": "PARSE_FAILED", "detail": str(ex),
            "artifacts": [art["sha256"]]})
    if got is not None:
        st = got[0]
        st["variant_version_id"] = vv["variant_version_id"]
        states.append(st)
    return {"filing": fx, "extras": base["extras"] if base else None,
            "extra_artifacts": extra_artifacts,
            "extension_mapping_files": ext_files, "states": states}


# ---- driver -----------------------------------------------------------------

def assemble_observation(manifest: dict, *,
                         tables: dict[str, list[dict]] | None = None,
                         evidence_root: Path,
                         tax_dir: Path | None = None,
                         work_dir: Path | None = None) -> dict:
    """Capture manifest -> CANONICAL_OBSERVATION_V1 document.

    ``tables`` is the base dataset's row dict; when None the observation
    is a full bootstrap projection (every filing fresh, every version
    parsed).
    """
    root = Path(evidence_root)
    ctx = _Ctx(tables, root, tax_dir,
               work_dir or (root / "_parse_work"),
               issuer_map=_issuer_map(manifest))
    filings_out: list[dict] = []

    per_reg: dict[str, dict[str, dict]] = {}
    issuer_of: dict[str, str] = {}
    for v in manifest.get("esef_views", []):
        per_reg.setdefault(v["registro"], {})[
            v["requested_ui_language"]] = v
        issuer_of[v["registro"]] = v["issuer_key"]
    walks = {w["registro"]: w
             for w in manifest.get("infadicion_walks", [])}
    for registro in sorted(per_reg):
        fid = ids.filing_id(registro, ids.IFA)
        views = per_reg[registro]
        key = issuer_of[registro]
        view_es = views.get("es")
        any_view = view_es or next(iter(views.values()))
        if view_es is None or view_es.get("status") is not None \
                or not view_es.get("package"):
            # no usable es anchor: the registry row exists but no
            # canonical filing can be built — classified, not dropped.
            reasons = sorted({v.get("status")
                              or v.get("resolution_mode") or "NO_VIEW"
                              for v in views.values()})
            ctx.unresolved.append(
                {"scope": "filing", "family": "ESEF_IFA",
                 "issuer_key": key, "nif": any_view.get("nif"),
                 "registro": registro, "filing_id": fid,
                 "period_end": any_view["registry_row"]["cells"][1],
                 "reason": "NO_USABLE_ANCHOR_VIEW",
                 "detail": "; ".join(reasons),
                 "artifacts": [v["package"]["sha256"]
                               for v in views.values()
                               if v.get("package")]})
            continue
        try:
            filings_out.append(assemble_esef(
                registro, views, walks.get(registro),
                key, _base_filing(ctx, fid), ctx))
        except CaptureError as ex:
            if ctx.tax_dir is None:
                raise   # operator error: parse requested without the
                        # pinned taxonomy input — fail closed
            ctx.unresolved.append(
                {"scope": "filing", "family": "ESEF_IFA",
                 "issuer_key": key, "nif": view_es.get("nif"),
                 "registro": registro, "filing_id": fid,
                 "reason": "ASSEMBLY_FAILED", "detail": str(ex),
                 "artifacts": []})

    for rec in manifest.get("ipp_filings", []):
        if rec.get("status") != "CAPTURED":
            continue
        fid = ids.filing_id(rec["nreg"], ids.IPP)
        try:
            fo = assemble_ipp(rec, _base_filing(ctx, fid), ctx)
        except CaptureError as ex:
            if ctx.tax_dir is None:
                raise   # operator error — fail closed
            ctx.unresolved.append(
                {"scope": "filing", "family": "IPP",
                 "issuer_key": rec["issuer_key"], "nif": rec.get("nif"),
                 "slot": rec.get("slot"), "nreg": rec.get("nreg"),
                 "filing_id": fid,
                 "reason": "ASSEMBLY_FAILED", "detail": str(ex),
                 "artifacts": ([rec["artifact"]["sha256"]]
                               if rec.get("artifact") else [])})
            continue
        if fo is not None:
            filings_out.append(fo)

    filings_out.sort(key=lambda fo: fo["filing"]["filing_id"])
    obs = {"observation_format": uobs.OBSERVATION_FORMAT,
           "observation_id": f"obs:{manifest['capture_id']}",
           "captured_at": manifest["captured_at"],
           "filings": filings_out}
    obs["observation_sha256"] = uobs.observation_sha256(obs)
    problems = uobs.validate(obs)
    if problems:
        raise CaptureError("assembled observation invalid: "
                           + "; ".join(problems[:8]))
    if ctx.warnings:
        obs["capture_warnings"] = ctx.warnings
    if ctx.unresolved:
        obs["unresolved"] = sorted(
            ctx.unresolved,
            key=lambda u: json.dumps(u, sort_keys=True,
                                     ensure_ascii=False))
    return obs
