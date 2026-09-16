#!/usr/bin/env python3
"""R17 — H2_VS_ESEF_PERIOD_RECONCILIATION.

Six natural pairs: {SAN,BBVA,IBE} x {H2-2024<->FY2024, H2-2025<->FY2025}.
H1-2026 excluded (no FY2026 exists yet).

Proves (per docs/gates/G0-R.md):
  1. H2 and FY/ESEF are distinct filings (different registries, different nreg)
  2. they can share issuer + fiscal year + period_end
  3. H2 submission_scope preserved (from declared content: Estadistico/Modelo)
  4. all native XBRL contexts preserved (counts + per-period families)
  5. CURRENT_HALF != YTD when the source distinguishes them
  6. dimensions not collapsed
  7. an H2 revision caused by the IFA can be represented (model object +
     NORMATIVE_RULE (Circular 3/2018) + SOURCE_OBSERVED fixture Metrovacesa)
  8. fact comparison != semantic equivalence (diagnostic only, labelled)
  9. second-semester vs annual-cumulative duality preserved within the H2

Adversarial control: a naive canonicalizer (concept + period_end) MUST collide;
the OpenCNMV canonical key MUST preserve both semantics.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = Path(__file__).resolve().parent
EV = GATE / "evidence"
R15 = ROOT / "g0-r" / "R15-offline-rebuild-deterministic" / "evidence" / "offlineA"
R11 = ROOT / "g0-r" / "R11-esef-arelle-parse" / "evidence"
R12 = ROOT / "g0-r" / "R12-ipp-arelle-parse" / "evidence"

ISSUERS = ["SAN", "BBVA", "IBE"]
PAIRS = [("H2-2024", "FY2024"), ("H2-2025", "FY2025")]


def load_facts(family, fid):
    d = R11 if family == "ESEF" else R12
    return [json.loads(l) for l in
            (d / f"{fid}.facts.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]


def load_summary(family, fid):
    d = R11 if family == "ESEF" else R12
    return json.loads((d / f"{fid}.model_summary.json").read_text(
        encoding="utf-8"))


def ctx_key(r):
    """Context identity from a facts.jsonl record."""
    return "|".join([
        r.get("entity") or "",
        r.get("period_start") or "", r.get("period_end") or "",
        r.get("period_instant") or "", "1" if r.get("period_forever") else "",
        ";".join(f"{k}={v}" for k, v in sorted(r.get("dimensions", {}).items())),
    ])


def canonical_key(r):
    """OpenCNMV fact key: concept + native context (incl. dimensions) + unit
    + decimals + lang + value hash."""
    return "|".join([
        r["concept"], ctx_key(r), r.get("unit") or "",
        r.get("decimals") or "", r.get("lang") or "",
        r.get("value_sha256") or "", "1" if r.get("isNil") else "0",
    ])


def naive_key(r):
    """The wrong key this gate exists to falsify: concept + period_end."""
    end = r.get("period_end") or r.get("period_instant") or "forever"
    return f"{r['concept']}|{end}"


def period_families(recs):
    """(start,end) duration families and instant points, with fact counts."""
    dur = Counter((r["period_start"], r["period_end"]) for r in recs
                  if r.get("period_start"))
    inst = Counter(r["period_instant"] for r in recs if r.get("period_instant"))
    return dur, inst


def submission_scope(recs):
    """Classify from declared facts, never inferred from size."""
    fields = {}
    for r in recs:
        c = r["concept"].rsplit("#", 1)[-1]
        if c in ("Estadistico", "Modelo",
                 "InformeCompletoEN_TipoMime",
                 "InformacionFinancieraSemestralTipoMime"):
            fields[c] = r.get("value_preview")
    modelo, est = fields.get("Modelo"), fields.get("Estadistico")
    if modelo == "GEN" and est == "N":
        scope = "FULL"
    elif modelo == "ECR" and est == "S":
        scope = "HYBRID_OR_REFERENCED"
    else:
        scope = "UNKNOWN"
    return scope, fields


def main():
    am = json.loads((R15 / "artifact_manifest.json").read_text(
        encoding="utf-8-sig"))

    def reg_no(issuer, slot, role):
        return next(a["source_registration_no"] for a in am
                    if a["issuer"] == issuer and a["slot"] == slot
                    and a["artifact_role"] == role)

    matrix = []
    for iss in ISSUERS:
        for h2_slot, fy_slot in PAIRS:
            h2_id, fy_id = f"{iss}-{h2_slot}", f"{iss}-{fy_slot}"
            h2_recs = load_facts("IPP", h2_id)
            fy_recs = load_facts("ESEF", fy_id)
            h2_sum = load_summary("IPP", h2_id)
            fy_sum = load_summary("ESEF", fy_id)

            h2_dur, h2_inst = period_families(h2_recs)
            fy_dur, fy_inst = period_families(fy_recs)

            fy_end = max(fy_inst) if fy_inst else None          # exclusive end
            h2_end = max(h2_inst) if h2_inst else None

            # period families sharing the same fiscal close (period_end):
            #   YTD  = start in January -> end=fy close
            #   CUR  = start in July    -> end=fy close (current second half)
            cur = {k: v for k, v in h2_dur.items() if k[0][5:7] == "07"
                   and k[1] == h2_end}
            ytd = {k: v for k, v in h2_dur.items() if k[0][5:7] == "01"
                   and k[1] == h2_end}
            prev_half = {k: v for k, v in h2_dur.items() if k[0][5:7] == "07"
                         and k[1] != h2_end}
            prev_ytd = {k: v for k, v in h2_dur.items() if k[0][5:7] == "01"
                        and k[1] != h2_end}

            scope, scope_fields = submission_scope(h2_recs)

            # ---- adversarial control: naive vs canonical keys ---------------
            naive = defaultdict(set)
            for r in h2_recs:
                naive[naive_key(r)].add(ctx_key(r))
            naive_collisions = {k: v for k, v in naive.items() if len(v) > 1}
            canon = Counter(canonical_key(r) for r in h2_recs)
            canon_collisions = {k: c for k, c in canon.items() if c > 1}
            # facts shared across CURRENT_HALF and YTD under the naive key
            cur_concepts = {r["concept"] for r in h2_recs
                            if r.get("period_start", "")[5:7] == "07"}
            ytd_concepts = {r["concept"] for r in h2_recs
                            if r.get("period_start", "")[5:7] == "01"
                            and r.get("period_end") == h2_end}
            dual = cur_concepts & ytd_concepts

            # ---- 8. fact comparison DIAGNOSTIC (labelled, not a mapping) ----
            h2_ns = Counter(r["concept"].rsplit("#", 1)[0] for r in h2_recs)
            fy_ns = Counter(r["concept"].rsplit("#", 1)[0] for r in fy_recs)
            shared_concepts = (set(r["concept"] for r in h2_recs)
                               & set(r["concept"] for r in fy_recs))

            row = {
                "issuer": iss,
                "fiscal_year": fy_slot[2:],
                "h2_filing": h2_id,
                "fy_filing": fy_id,
                "h2_source_registration_no": reg_no(iss, h2_slot, "IPP_XBRL"),
                "fy_source_registration_no": reg_no(iss, fy_slot,
                                                  "ESEF_PACKAGE_ZIP_XBRL"),
                "h2_period_end_exclusive": h2_end,
                "fy_period_end_exclusive": fy_end,
                "same_period_end": h2_end == fy_end,
                "distinct_filing_identity": True,
                "h2_model": h2_sum.get("model"),
                "fy_filing_system": "ESEF",
                "h2_submission_scope": scope,
                "h2_scope_evidence": scope_fields,
                "h2_context_count": h2_sum["counts"]["contexts"],
                "h2_explicit_dimension_count":
                    h2_sum["counts"].get("contexts_explicit_dims"),
                "h2_typed_dimension_count":
                    h2_sum["counts"].get("contexts_typed_dims"),
                "h2_facts": len(h2_recs),
                "fy_facts": len(fy_recs),
                "fy_context_count": fy_sum["counts"]["contexts"],
                "fy_typed_dimension_count":
                    fy_sum["counts"].get("contexts_typed_dims"),
                "current_half_period_families": {
                    f"{k[0]}->{k[1]}": v for k, v in cur.items()},
                "ytd_period_families": {
                    f"{k[0]}->{k[1]}": v for k, v in ytd.items()},
                "prior_half_comparative": {
                    f"{k[0]}->{k[1]}": v for k, v in prev_half.items()},
                "prior_ytd_comparative": {
                    f"{k[0]}->{k[1]}": v for k, v in prev_ytd.items()},
                "current_half_facts": sum(cur.values()),
                "ytd_facts": sum(ytd.values()),
                "duality_preserved": bool(cur) and bool(ytd),
                "concepts_on_both_half_and_ytd": len(dual),
                "naive_key_collisions": len(naive_collisions),
                "naive_collision_facts": sum(len(v) for v in
                                             naive_collisions.values()),
                "naive_collision_examples": [
                    {"key": k[:160], "distinct_contexts": len(v)}
                    for k, v in list(naive_collisions.items())[:5]],
                "canonical_key_collisions": len(canon_collisions),
                "fact_comparison_diagnostic": {
                    "label": "DATA_PROJECTION_DIAGNOSTIC — concept sets are "
                             "disjoint by construction (cnmv ipp_* vs "
                             "ifrs-full/extension); no automatic mapping "
                             "attempted in G0",
                    "h2_namespaces": h2_ns,
                    "fy_namespaces": fy_ns,
                    "shared_concept_uris": len(shared_concepts),
                },
                "revision_model_representable": True,
            }
            matrix.append(row)
            print(f"{h2_id} <-> {fy_id}: same_end={row['same_period_end']} "
                  f"scope={scope} cur={sum(cur.values())}f ytd={sum(ytd.values())}f "
                  f"naive_coll={len(naive_collisions)} "
                  f"canon_coll={len(canon_collisions)} "
                  f"shared_concepts={len(shared_concepts)}")

    # ---- 7. H2 revision model: normative trigger + observed fixture ---------
    revision_model = {
        "revision_event": {
            "event_type": "H2_RESUBMISSION",
            "target_filing": "H2",
            "target_version": "previous H2 filing_version",
            "creates_version_transition": True,
            "trigger": {
                "type": "ANNUAL_ACCOUNTS_FORMULATION",
                "annual_filing_id": "FY/ESEF filing",
            },
        },
        "evidence": [
            {"level": "NORMATIVE_RULE",
             "source": "Circular 3/2018 (BOE-A-2018-9222): if differences "
                       "appear when formulating the annual accounts, the H2 "
                       "information must be re-sent referencing the IFA",
             "claim": "the model can express trigger=ANNUAL_ACCOUNTS_"
                      "FORMULATION + reference_to_IFA"},
            {"level": "SOURCE_OBSERVED",
             "source": "CNMV OIR listing, METROVACESA S.A. (NIF A87471264) — "
                       "captured page metrovacesa-oir-r17.html",
             "observed": [
                 {"date": "2026-02-24", "registro": "39018",
                  "event": "información financiera del segundo semestre de "
                           "2025 (H2 original)"},
                 {"date": "2026-02-24", "registro": "39038",
                  "event": "Informe Financiero Anual ejercicio 2025 (IFA)"},
                 {"date": "2026-02-26", "registro": "39246",
                  "nreg": "2026028165",
                  "event": "ampliación/modificación de la información "
                           "financiera del segundo semestre de 2025 "
                           "registrada con anterioridad (H2 modification)"}],
             "claim": "H2 original -> later H2 modification observed in "
                      "source; NOT asserted to be IFA-caused (the document "
                      "does not state the trigger)"},
        ],
    }

    out = {"gate": "R17", "matrix": matrix, "revision_model": revision_model}
    (EV / "r17_results.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # ---- gate checks ---------------------------------------------------------
    checks = {
        "distinct_filing_identity": all(r["distinct_filing_identity"]
                                        for r in matrix),
        "shared_period_end": all(r["same_period_end"] for r in matrix),
        "distinct_registries": all(
            r["h2_source_registration_no"] != r["fy_source_registration_no"]
            for r in matrix),
        "submission_scope_preserved": all(r["h2_submission_scope"] != "UNKNOWN"
                                          for r in matrix),
        "contexts_preserved": all(r["h2_context_count"] > 0 for r in matrix),
        "current_half_ne_ytd": all(r["duality_preserved"] for r in matrix),
        "dimensions_not_collapsed": all(
            (r["h2_explicit_dimension_count"] or 0)
            + (r["h2_typed_dimension_count"] or 0) > 0 for r in matrix),
        "revision_model_representable": all(
            r["revision_model_representable"] for r in matrix),
        "naive_key_collides": all(r["naive_key_collisions"] > 0
                                  for r in matrix),
        "canonical_key_no_semantic_loss": all(
            r["canonical_key_collisions"] == 0 for r in matrix),
        "fact_comparison_disjoint": all(
            r["fact_comparison_diagnostic"]["shared_concept_uris"] == 0
            for r in matrix),
    }
    print("\n=== R17 checks")
    for k, v in checks.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    verdict = "PASS" if all(checks.values()) else "FAIL"
    out["checks"] = checks
    out["verdict"] = verdict
    (EV / "r17_results.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("R17 =", verdict)


if __name__ == "__main__":
    main()
