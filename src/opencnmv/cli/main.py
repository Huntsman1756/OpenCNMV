"""``opencnmv`` — deterministic read-only CLI over COLUMNAR_DATASET_V1.

Thin presentation layer: every callback resolves the dataset, calls an
``opencnmv.query`` function, and renders the returned dict. No domain
semantics live here; nothing writes to the dataset or the network.
"""
from __future__ import annotations

import argparse
import sys

import opencnmv
from opencnmv.cli import errors as cerr
from opencnmv.cli import formatting as fmt
from opencnmv.query.errors import (MissingDependencyError, QueryError,
                                   UsageError)


def _query():
    """Import the query surface lazily so `--help`/`--version` and usage
    errors work without the optional duckdb/pyarrow dependencies; a
    missing dep surfaces as exit 6, not a traceback."""
    try:
        from opencnmv.query import compare, dataset, events, facts, \
            filings, history, mappings, provenance
    except ImportError as e:
        raise MissingDependencyError(
            f"{e.name or 'a dependency'} is required for dataset "
            "commands; install the 'dataset' extra "
            "(pip install opencnmv[dataset])") from e
    return compare, dataset, events, facts, filings, history, \
        mappings, provenance

# ---------------------------------------------------------------- human
# renderers: dict -> deterministic terminal text


def _r_dataset_info(info: dict) -> str:
    m = info
    out = [fmt.kv([
        ("dataset", m["dataset"]),
        ("dataset_version", m["dataset_version"]),
        ("canonical_model", m["canonical_model"]),
        ("corpus_logical_sha256", m["corpus_logical_sha256"]),
        ("schema_fingerprint", m["schema_fingerprint"]),
        ("code_commit", m["code_commit"]),
        ("generator", (m.get("generator") or {}).get("name")),
        ("manifest_verified", m["integrity"]["manifest_verified"]),
    ])]
    out.append("")
    out.append(fmt.table(
        ["table", "rows"],
        [[t, m["tables"][t]["rows"]] for t in
         sorted(m["tables"], key=lambda t: list(m["tables"]).index(t))]))
    out.append("")
    out.append(fmt.kv([(k, v) for k, v in m["counts"].items()]))
    return "\n".join(out)


def _r_dataset_validate(rep: dict) -> str:
    out = [fmt.kv([
        ("status", rep["status"]),
        ("dataset_version", rep["dataset_version"]),
        ("canonical_model", rep["canonical_model"]),
        ("corpus_logical_sha256", rep["corpus_logical_sha256"]),
    ]), ""]
    out.append(fmt.table(
        ["check", "status", "detail"],
        [[c["name"], c["status"], c["detail"]] for c in rep["checks"]]))
    return "\n".join(out)


def _r_filings(rows: list[dict]) -> str:
    return fmt.table(
        ["filing_id", "issuer", "family", "period_end", "variants",
         "versions", "facts"],
        [[r["filing_id"], r["issuer_denomination"], r["family"],
          r["period_end_iso"], r["variants"], r["variant_versions"],
          r["facts"]] for r in rows]) + f"\n{len(rows)} filing(s)"


def _r_filing(d: dict) -> str:
    f = d["filing"]
    out = [fmt.kv([
        ("filing_id", f["filing_id"]),
        ("issuer", f["issuer"].get("denomination")),
        ("nif", f["issuer"].get("nif")),
        ("lei", f["issuer"].get("lei")),
        ("registro_oficial", f["registro_oficial"]),
        ("family", f["family"]),
        ("period_end", f["period_end"]),
    ])]
    for fv in f["filing_versions"]:
        out += ["", "filing_version",
                fmt.kv([
                    ("  id", fv["filing_version_id"]),
                    ("  source_nreg", fv["source_nreg"]),
                    ("  filed_at", fv["filed_at"]),
                    ("  submission_kind", fv["submission_kind"]),
                    ("  artifacts", len(fv.get("artifacts") or [])),
                ])]
    for v in f["submission_variants"]:
        out += ["", f"variant {v['variant_id']} "
                f"(submission_language={v['submission_language']})"]
        for vv in v["variant_versions"]:
            sup = vv["supersedes_variant_version_id"] or "-"
            out.append(
                f"  {vv['variant_version_id']}  observed={vv['observed']}"
                f"  artifacts={len(vv['artifacts'])}"
                f"  supersedes={sup}"
                f"  created_by={vv['created_by_event_id'] or '-'}")
    for vr in f["view_resolutions"]:
        out.append(f"view_resolution  ui={vr['requested_ui_language']} "
                   f"-> {vr['resolved_variant_id']} "
                   f"({vr['resolution_mode']})")
    for e in f["version_events"]:
        out += ["", f"event {e['event_id']}",
                fmt.kv([
                    ("  date", e["event_date"]),
                    ("  type", e["event_type"]),
                    ("  scope_status", e["scope_status"]),
                    ("  source_nreg", e["source_nreg"]),
                    ("  source_label", e["source_label"]),
                ])]
        for a in e["affects"]:
            out.append(
                f"    affects {a['variant_id'] or '?'} "
                f"scope={a['affected_component_scope']} "
                f"{a['before_variant_version_id'] or '-'} -> "
                f"{a['after_variant_version_id'] or '-'}")
    if d.get("extension_mapping_summary"):
        out += ["", "extension_mappings " +
                " ".join(f"{k}={v}" for k, v in sorted(
                    d["extension_mapping_summary"].items()))]
    out += ["", fmt.table(
        ["state_id", "variant_version", "role", "facts",
         "evidence_path"],
        [[s["state_id"], s["variant_version_id"], s["role"],
          s["fact_count"], s["evidence_path"]] for s in d["states"]])]
    return "\n".join(out)


def _r_history(h: dict) -> str:
    out = [f"filing {h['filing_id']}"]
    for v in h["variants"]:
        out.append(f"\n{v['variant_id']}  "
                   f"(submission_language={v['submission_language']})")
        for vv in v["versions"]:
            sup = (f"  supersedes "
                   f"{vv['supersedes_variant_version_id']}"
                   if vv["supersedes_variant_version_id"] else "")
            out.append(
                f"  v{vv['version_seq']}  {vv['variant_version_id']}  "
                f"observed={vv['observed']}  "
                f"artifacts={vv['artifact_count']}  "
                f"facts={vv['fact_count']}{sup}")
        for vr in v["view_resolutions"]:
            out.append(f"  view_resolution ui={vr['requested_ui_language']}"
                       f" ({vr['resolution_mode']})")
    for e in h["version_events"]:
        out += ["", f"event {e['event_date']}  {e['event_type']}  "
                f"scope_status={e['scope_status']}  "
                f"source_nreg={e['source_nreg'] or 'null'}",
                f"  source_label: {e['source_label']}"]
        for a in e["affects"]:
            out.append(
                f"  affects {a['variant_id'] or '(unobservable)'}  "
                f"{a['affected_component_scope']}  "
                f"{a['before_variant_version_id'] or '-'} -> "
                f"{a['after_variant_version_id'] or '-'}"
                f"  basis={a['scope_basis']}")
    return "\n".join(out)


def _fact_line(r: dict) -> list:
    dims = ";".join(f"{d['dim_qname']}={d['dim_kind']}:"
                    f"{d['member_qname'] or d['typed_value']}"
                    for d in r["dimensions"])
    return [r["fact_id"], r["state_id"], r["concept"],
            r["period_end"] or r["period_instant"] or
            ("forever" if r["period_forever"] else ""),
            r["lang"], r["unit"] or "-", dims or "-",
            r["decimals"] if r["decimals"] is not None else "-",
            "nil" if r["isNil"] else (r["value_preview"] or "")]


def _r_facts(res: dict) -> str:
    out = [fmt.table(
        ["fact_id", "state", "concept", "period", "lang", "unit",
         "dimensions", "dec", "value"],
        [_fact_line(r) for r in res["facts"]])]
    tail = f"\n{len(res['facts'])} of {res['total']} fact(s)"
    if res["truncated"]:
        tail += f" (limit {res['limit']}; pass --limit 0 for all)"
    return out[0] + tail


def _r_fact(d: dict) -> str:
    r = d
    out = [fmt.kv([
        ("fact_id", r["fact_id"]),
        ("state_id", r["state_id"]),
        ("variant_version_id", r["variant_version_id"]),
        ("seq", r["seq"]),
        ("concept", r["concept"]),
        ("concept_type", r["concept_type"]),
        ("ns_kind", r["ns_kind"]),
        ("is_numeric", r["is_numeric"]),
        ("entity_scheme", r["entity_scheme"]),
        ("entity", r["entity"]),
        ("period_start", r["period_start"]),
        ("period_end", r["period_end"]),
        ("period_instant", r["period_instant"]),
        ("period_forever", r["period_forever"]),
        ("contextID", r["contextID"]),
        ("unit", r["unit"]),
        ("unit_numerator", "*".join(r["unit_numerator"]) or None),
        ("unit_denominator", "*".join(r["unit_denominator"]) or None),
        ("unitID", r["unitID"]),
        ("lang", r["lang"]),
        ("decimals", r["decimals"]),
        ("isNil", r["isNil"]),
        ("value_sha256", r["value_sha256"]),
        ("xValue_sha256", r["xValue_sha256"]),
        ("structural_key_multiplicity", r["structural_key_multiplicity"]),
    ])]
    if r["dimensions"]:
        out += ["", "dimensions",
                fmt.table(["dim_qname", "kind", "member_qname",
                           "typed_value"],
                          [[x["dim_qname"], x["dim_kind"],
                            x["member_qname"], x["typed_value"]]
                           for x in r["dimensions"]])]
    v = r["value_full"] if r["value_full"] is not None \
        else r["value_preview"]
    if v is not None:
        out += ["", f"value: {v}"]
    for p in r["provenance"]:
        out += ["", f"provenance role={p['role']} "
                f"artifact={p['artifact_id']}",
                f"  sha256={p['sha256']}",
                f"  evidence_path={p['evidence_path']}"]
    return "\n".join(out)


def _r_compare(rep: dict) -> str:
    out = [fmt.kv([("filing_id", rep["filing_id"]),
                   ("status", rep["status"])])]
    if rep["status"] != "COMPARED":
        out.append(rep["note"])
        for vr in rep["view_resolutions"]:
            out.append(f"view_resolution ui={vr['requested_ui_language']}"
                       f" -> {vr['resolved_variant_id']}"
                       f" ({vr['resolution_mode']})")
        return "\n".join(out)
    out.append("")
    for lg, s in rep["compared"].items():
        out.append(f"{lg}: {s['variant_version_id']}  "
                   f"{s['facts']} facts")
    out += ["", f"proven pairs applied: {rep['proven_pairs_applied']}",
            fmt.kv([(k, v) for k, v in rep["counts"].items()]),
            f"match_exact (keys): {rep['match_exact_count']}", ""]
    rows = []
    for r in rep["records"]:
        sides = [lg for lg in rep["compared"] if lg in r]
        es_v = next((r[s]["value"] for s in sides), None)
        en_v = (r[sides[1]]["value"] if len(sides) > 1 else None)
        rows.append([r["class"], r["key"]["concept"],
                     r["key"]["period"], r.get("variant") or "",
                     es_v, en_v])
    out.append(fmt.table(["class", "concept", "period", "side",
                          "value_a", "value_b"], rows, max_width=48))
    return "\n".join(out)


def _r_events(rows: list[dict]) -> str:
    out = [fmt.table(
        ["event_id", "date", "type", "scope_status", "source_nreg"],
        [[e["event_id"], e["event_date"], e["event_type"],
          e["scope_status"], e["source_nreg"]] for e in rows])]
    for e in rows:
        for a in e["affects"]:
            out.append(f"{e['event_id']}: affects "
                       f"{a['variant_id'] or '(unobservable)'} "
                       f"{a['affected_component_scope']} "
                       f"{a['before_variant_version_id'] or '-'} -> "
                       f"{a['after_variant_version_id'] or '-'}")
    return "\n".join(out)


def _r_mappings(rep: dict) -> str:
    out = [rep["rule"], "",
           fmt.kv([(k, v) for k, v in
                   sorted(rep["counts_by_verdict"].items())]), ""]
    out.append(fmt.table(
        ["verdict", "rewrites", "source_qname", "target_qname",
         "pair_id"],
        [[m["verdict"], m["rewrites_identity"], m["source_qname"],
          m["target_qname"], m["pair_id"]] for m in rep["mappings"]],
        max_width=56))
    return "\n".join(out)


def _r_prov(rep: dict) -> str:
    out = [fmt.kv([(k, v) for k, v in rep.items()
                   if k != "provenance" and k != "artifact_rows"
                   and k != "structural_identity"])]
    if rep.get("structural_identity"):
        out += ["", "structural_identity",
                fmt.kv([(k, v) for k, v in
                        rep["structural_identity"].items()])]
    for a in rep.get("artifact_rows", []):
        out.append(f"\nartifact owner={a['owner_kind']}:{a['owner_id']} "
                   f"role={a['role']} sha256={a['sha256']}")
    for c in rep["provenance"]:
        sa = c["source_artifact"]
        out += ["", f"role={c['role']}",
                fmt.kv([
                    ("  state_id", c["context"]["state_id"]),
                    ("  variant_version_id",
                     c["context"]["variant_version_id"]),
                    ("  artifact_id", sa["artifact_id"]),
                    ("  sha256", sa["sha256"]),
                    ("  media_type", sa["media_type"]),
                    ("  source_url", sa["source_url"]),
                    ("  retrieved_at", sa["retrieved_at"]),
                    ("  http_status", sa["http_status"]),
                    ("  evidence_path", sa["evidence_path"]),
                    ("  arelle_version", c["parse"]["arelle_version"]),
                ])]
    return "\n".join(out)


# ---------------------------------------------------------------- parser

def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--dataset", default=argparse.SUPPRESS,
                   help="path to a COLUMNAR_DATASET_V1 directory")
    p.add_argument("--json", action="store_true",
                   default=argparse.SUPPRESS,
                   help="emit a single deterministic JSON document")
    p.add_argument("--jsonl", action="store_true",
                   default=argparse.SUPPRESS,
                   help="emit one JSON object per line (list commands)")
    p.add_argument("--debug", action="store_true",
                   default=argparse.SUPPRESS,
                   help="re-raise errors instead of formatted messages")
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    p = argparse.ArgumentParser(
        prog="opencnmv",
        description="Deterministic read-only CLI over a materialized "
                    "COLUMNAR_DATASET_V1. Never writes, never touches "
                    "the network. Docs: docs/CLI.md",
        parents=[common])
    p.add_argument("--version", action="version",
                   version=f"opencnmv {opencnmv.__version__} "
                           f"({opencnmv.MODEL_CONTRACT})")
    sub = p.add_subparsers(dest="command", metavar="command")

    ds = sub.add_parser("dataset", help="dataset information/validation")
    dsub = ds.add_subparsers(dest="subcommand", metavar="action")
    dsub.add_parser("info", parents=[common],
                    help="manifest-backed dataset summary")
    dsub.add_parser("validate", parents=[common],
                    help="manifest + logical-hash + referential checks")

    f = sub.add_parser("filings", parents=[common],
                       help="list filings (deterministic order)")
    f.add_argument("--issuer", help="substring of issuer denomination")
    f.add_argument("--nif", help="exact issuer NIF")
    f.add_argument("--lei", help="exact issuer LEI")
    f.add_argument("--family", help="exact family (e.g. IPP, ESEF)")
    f.add_argument("--period", help="exact period_end date")
    f.add_argument("--from", dest="date_from",
                   help="period_end >= date (ISO or dd/mm/yyyy)")
    f.add_argument("--to", dest="date_to",
                   help="period_end <= date (ISO or dd/mm/yyyy)")

    fl = sub.add_parser("filing", parents=[common],
                        help="canonical filing detail")
    fl.add_argument("ref", help="filing_id or registro_oficial")

    h = sub.add_parser("history", parents=[common],
                       help="variant/version lifecycle + events")
    h.add_argument("ref", help="filing_id, registro_oficial or "
                               "variant_id")

    fx = sub.add_parser("facts", parents=[common],
                        help="fact query (multiset-preserving)")
    fx.add_argument("--filing", help="filing ref")
    fx.add_argument("--variant",
                    help="variant_id, or bare lang with --filing")
    fx.add_argument("--state", help="state_id (e.g. SAN-H1-2024)")
    fx.add_argument("--concept", help="concept QName substring")
    fx.add_argument("--period", help="period_end or instant date")
    fx.add_argument("--lang", help="xml:lang value")
    fx.add_argument("--dims", help="substring of canonical dims JSON")
    fx.add_argument("--unit", help="unit signature substring")
    fx.add_argument("--nil", action="store_true",
                    help="only isNil facts")
    fx.add_argument("--limit", type=int, default=100,
                    help="max rows (default 100; 0 = no limit)")
    fx.add_argument("--count", action="store_true",
                    help="print only the matching row count")

    fa = sub.add_parser("fact", parents=[common],
                        help="one fact: full record + dimensions + "
                             "provenance")
    fa.add_argument("fact_id", help="canonical fact_id")

    cm = sub.add_parser("compare", parents=[common],
                        help="semantic cross-variant comparison")
    cm.add_argument("ref", help="filing_id or registro_oficial")
    cm.add_argument("--class", dest="cls", metavar="C",
                    help="only records of this comparison class "
                         "(e.g. DIVERGENT_SUBMISSION_FACT)")
    cm.add_argument("--limit", type=int, default=0,
                    help="max records (0 = all)")

    ev = sub.add_parser("events", parents=[common],
                        help="version events")
    ev.add_argument("ref", nargs="?", default=None,
                    help="filing_id or registro_oficial")

    mp = sub.add_parser("mappings", parents=[common],
                        help="extension mappings + verdicts")
    mp.add_argument("ref", help="filing_id or registro_oficial")
    mp.add_argument("--verdict", help="exact verdict filter")

    pv = sub.add_parser("provenance", parents=[common],
                        help="trace a canonical row to pinned evidence")
    g = pv.add_mutually_exclusive_group(required=True)
    g.add_argument("--fact", help="fact_id")
    g.add_argument("--artifact", help="artifact_id (sha256:<hex>)")
    g.add_argument("--state", help="state_id")

    return p


# ---------------------------------------------------------------- dispatch

def _emit(args, obj, human, jsonl_rows=None) -> int:
    if getattr(args, "jsonl", False):
        fmt.emit_jsonl(jsonl_rows if jsonl_rows is not None else obj)
    elif getattr(args, "json", False):
        fmt.emit_json(obj)
    else:
        sys.stdout.write(human(obj) + "\n")
    return cerr.EXIT_OK


def _open(args, qds):
    path = qds.resolve_dataset_path(getattr(args, "dataset", None))
    return qds.open_dataset(path)


def _run(args) -> int:
    qcompare, qds, qevents, qfacts, qfilings, qhistory, qmappings, \
        qprov = _query()
    if args.command == "dataset":
        if args.subcommand == "info":
            with _open(args, qds) as ds:
                return _emit(args, qds.dataset_info(ds), _r_dataset_info)
        if args.subcommand == "validate":
            with _open(args, qds) as ds:
                rep = qds.validate_dataset(ds)
            _emit(args, rep, _r_dataset_validate)
            return (cerr.EXIT_OK if rep["status"] == "PASS"
                    else cerr.EXIT_INTEGRITY)
        raise QueryError("dataset requires an action: info | validate")
    if args.command == "filings":
        with _open(args, qds) as ds:
            rows = qfilings.list_filings(
                ds, issuer=args.issuer, nif=args.nif, lei=args.lei,
                family=args.family, period=args.period,
                date_from=args.date_from, date_to=args.date_to)
        return _emit(args, rows, _r_filings, jsonl_rows=rows)
    if args.command == "filing":
        with _open(args, qds) as ds:
            return _emit(args, qfilings.filing_detail(ds, args.ref),
                         _r_filing)
    if args.command == "history":
        with _open(args, qds) as ds:
            return _emit(args, qhistory.filing_history(ds, args.ref),
                         _r_history)
    if args.command == "facts":
        with _open(args, qds) as ds:
            res = qfacts.query_facts(
                ds, filing=args.filing, variant=args.variant,
                state=args.state, concept=args.concept,
                period=args.period, lang=args.lang, dims=args.dims,
                unit=args.unit, nil=args.nil, limit=args.limit,
                count_only=args.count)
        if args.count:
            if getattr(args, "json", False) or getattr(args, "jsonl",
                                                      False):
                return _emit(args, res, None, jsonl_rows=[res])
            sys.stdout.write(f"{res['total']}\n")
            return cerr.EXIT_OK
        return _emit(args, res, _r_facts, jsonl_rows=res["facts"])
    if args.command == "fact":
        with _open(args, qds) as ds:
            return _emit(args, qfacts.get_fact(ds, args.fact_id),
                         _r_fact)
    if args.command == "compare":
        if args.cls and args.cls not in qcompare.CLASSES:
            raise UsageError(
                f"invalid --class {args.cls!r}; choose from "
                + ", ".join(qcompare.CLASSES))
        with _open(args, qds) as ds:
            rep = qcompare.compare_filing(ds, args.ref)
        if args.cls:
            rep["records"] = [r for r in rep["records"]
                              if r["class"] == args.cls]
        if args.limit:
            rep["records"] = rep["records"][:args.limit]
            rep["records_truncated"] = True
        return _emit(args, rep, _r_compare)
    if args.command == "events":
        with _open(args, qds) as ds:
            rows = qevents.filing_events(ds, args.ref)
        return _emit(args, rows, _r_events, jsonl_rows=rows)
    if args.command == "mappings":
        with _open(args, qds) as ds:
            rep = qmappings.filing_mappings(ds, args.ref,
                                            verdict=args.verdict)
        return _emit(args, rep, _r_mappings,
                     jsonl_rows=rep["mappings"])
    if args.command == "provenance":
        with _open(args, qds) as ds:
            if args.fact:
                rep = qprov.fact_provenance(ds, args.fact)
            elif args.artifact:
                rep = qprov.artifact_provenance(ds, args.artifact)
            else:
                rep = qprov.state_provenance(ds, args.state)
        return _emit(args, rep, _r_prov)
    raise QueryError("no command given; see `opencnmv --help`")


def entry(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) is None:
        build_parser().print_help()
        return cerr.EXIT_USAGE
    try:
        return _run(args)
    except QueryError as e:
        if getattr(args, "debug", False):
            raise
        print(f"error: {e}", file=sys.stderr)
        return cerr.exit_code_for(e)
    except BrokenPipeError:
        return cerr.EXIT_OK
    except Exception as e:  # noqa: BLE001 — never a bare traceback
        if getattr(args, "debug", False):
            raise
        print(f"error: internal: {type(e).__name__}: {e}",
              file=sys.stderr)
        return cerr.EXIT_INTERNAL


def main() -> None:
    raise SystemExit(entry())
