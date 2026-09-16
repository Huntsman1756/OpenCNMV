# G1-D — builds g1d_results.json deterministically from preserved evidence:
#   g1d_scan.json / g1d_scan2.json (candidate discovery),
#   g1d_capture.json (phase-1 variant classification of the FY2025 candidates),
#   g1d_tef20484.json (full TEF-20484 capture) and the preserved cert .txt.
#
# Scope rule (preregistered):
#   EN_ONLY_REPLACED / ES_ONLY_REPLACED  <- reason clause explicitly scopes the
#       replaced artefact to one language variant.
#   BOTH_VARIANTS_REPLACED             <- only with explicit evidence that both
#       artefact sets were replaced (never inferred from shared registry/dates).
#   VARIANT_SCOPE_NOT_OBSERVABLE       <- otherwise.
from __future__ import annotations

import hashlib, json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"

SCOPE_VOCAB = ["BOTH_VARIANTS_REPLACED", "ES_ONLY_REPLACED",
               "EN_ONLY_REPLACED", "VARIANT_SCOPE_NOT_OBSERVABLE"]


def sha256_file(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def reason_clause(txt, anchor=None):
    # capture the reason clause to end of paragraph (\n\n or "Y, para que"),
    # so periods inside "S.A." / "20484." do not truncate it
    if anchor:
        m = re.search(anchor + r".*?motivo de la sustituci[oó]n es\s+"
                      r"(.+?)(?:\n\s*\n|Y,\s*para)", txt, re.S | re.I)
    else:
        m = re.search(r"motivo de la sustituci[oó]n\s+(?:es|fue)\s+"
                      r"(.+?)(?:\n\s*\n|Y,\s*para)", txt, re.S | re.I)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".")


def classify_scope(reason):
    if not reason:
        return "VARIANT_SCOPE_NOT_OBSERVABLE", "no reason clause extracted"
    en = re.search(r"versi[oó]n en ingl[eé]s", reason, re.I)
    es = re.search(r"versi[oó]n en (espa[nñ]ol|castellano)", reason, re.I)
    if en and not es:
        return "EN_ONLY_REPLACED", \
            "reason clause explicitly scopes the replaced artefact to the " \
            "English published version"
    if es and not en:
        return "ES_ONLY_REPLACED", \
            "reason clause explicitly scopes the replaced artefact to the " \
            "Spanish published version"
    if en and es:
        return "BOTH_VARIANTS_REPLACED", \
            "reason clause references both language versions"
    return "VARIANT_SCOPE_NOT_OBSERVABLE", \
        "reason clause does not identify the affected artefact set at " \
        "variant granularity"


def main():
    tef = json.loads((HERE / "g1d_tef20484.json").read_text(encoding="utf-8"))
    scan2 = json.loads((HERE / "g1d_scan2.json").read_text(encoding="utf-8"))
    scan1 = json.loads((HERE / "g1d_scan.json").read_text(encoding="utf-8"))
    cap = json.loads((HERE / "g1d_capture.json").read_text(encoding="utf-8"))

    res2 = scan2["results"]
    duals = [{"denom": r["denom"], "nregaud": r["nregaud"],
              "period_end": r["period_end"]}
             for r in res2 if r.get("dual_zip_token")]
    subs = [{"denom": r["denom"], "nregaud": r["nregaud"],
             "period_end": r["period_end"],
             "substitution_rows": len(r["substitutions"])}
            for r in res2 if r.get("substitutions")]
    hits = [{"denom": r["denom"], "nregaud": r["nregaud"],
             "period_end": r["period_end"]}
            for r in res2
            if r.get("dual_zip_token") and r.get("substitutions")]

    # --- candidate classification (phase 1 mechanism) -------------------
    candidates = []
    cap_by_issuer = {r["issuer"]: r for r in cap["results"]}
    scan1_by = {r["denom"]: r for r in scan1["results"]}
    for iss, reg in (("AMPER", "20938"), ("BANKINTER", "20860"),
                     ("URBAR", "21257")):
        c = cap_by_issuer.get(iss, {})
        v = c.get("verdict_p1")
        method = "PACKAGE_LANG_TAG"
        if v in (None, "UNRESOLVED"):
            # fallback evidence: identical zip token served under both UI langs
            s1 = scan1_by.get(iss, {})
            v = ("SINGLE_VARIANT_WITH_UI_FALLBACK"
                 if s1.get("zip_token_equal") else "UNRESOLVED")
            method = "ZIP_TOKEN_EQUAL"
        candidates.append({
            "issuer": iss, "nregaud": reg, "verdict": v,
            "classification_method": method,
            "substitution_rows": next(
                (s["substitution_rows"] for s in subs
                 if s["nregaud"] == reg), None),
            "can_falsify": v == "DUAL_VARIANT_SHARED_REGISTRY"})
    candidates.append({
        "issuer": "TELEFONICA", "nregaud": "20484",
        "verdict": tef["verdict_p1"],
        "classification_method": "PACKAGE_LANG_TAG+PACKAGE_SHA256",
        "submitted_variants": tef["submitted_variants"],
        "package_sha256": {
            "es": next(d["sha256"] for d in tef["phase1"]["es"]["docs"]
                       if d["kind"] == "ESEF_PACKAGE_ZIP"),
            "en": next(d["sha256"] for d in tef["phase1"]["en"]["docs"]
                       if d["kind"] == "ESEF_PACKAGE_ZIP")},
        "can_falsify": True})

    # --- TEF-20484 event records -----------------------------------------
    # e1 (13/03/2025, label "otros") recounts BOTH substitutions; e3
    # (28/02/2025, label "sustitución") covers only the first.
    events = []
    e1_txt = (EV / "doc-TEF-20484-es-e1-0.txt").read_text(encoding="utf-8")
    e3_txt = (EV / "doc-TEF-20484-es-e3-0.txt").read_text(encoding="utf-8")

    r3 = reason_clause(e3_txt)
    s3, why3 = classify_scope(r3)
    events.append({
        "event_date": "2025-02-28",
        "event_label": "Certificado del secretario del consejo sobre la "
                       "sustitución del informe financiero anual",
        "doc": "doc-TEF-20484-es-e3-0.pdf",
        "doc_sha256": sha256_file(EV / "doc-TEF-20484-es-e3-0.pdf"),
        "replaces_nreg": "2025030764",
        "new_nreg": "2025031622",
        "reason_clause": r3,
        "reason_scopes_language": bool(
            r3 and re.search(r"ingl[eé]s|espa[nñ]ol|castellano", r3, re.I)),
        "scope": s3, "scope_basis": why3})

    r1 = reason_clause(
        e1_txt,
        anchor=r"se est[aá] sustituyendo el Informe Financiero Anual.*?"
               r"remitido el 28 de febrero de 2025")
    s1, why1 = classify_scope(r1)
    events.append({
        "event_date": "2025-03-13",
        "event_label": "Otra información complementaria (Otros)  "
                       "[label is not 'sustitución'; doc content is a "
                       "substitution certificate]",
        "doc": "doc-TEF-20484-es-e1-0.pdf",
        "doc_sha256": sha256_file(EV / "doc-TEF-20484-es-e1-0.pdf"),
        "replaces_nreg": "2025031622",
        "new_nreg": None,
        "reason_clause": r1,
        "reason_scopes_language": bool(
            r1 and re.search(r"ingl[eé]s|espa[nñ]ol|castellano", r1, re.I)),
        "scope": s1, "scope_basis": why1})

    doc_pairs = tef["phase3"]["event_doc_bytes_equal_es_vs_en"]
    nreg_history = [
        {"nreg": "2025030764", "submitted": "2025-02-27",
         "kind": "ORIGINAL_SUBMISSION"},
        {"nreg": "2025031622", "submitted": "2025-02-28",
         "kind": "SUBSTITUTION", "replaces": "2025030764",
         "scope": events[0]["scope"]},
        {"nreg": None, "submitted": "2025-03-13",
         "kind": "SUBSTITUTION", "replaces": "2025031622",
         "scope": events[1]["scope"]}]

    filing_verdict = (
        "INDEPENDENT_VARIANT_LIFECYCLE_PROVEN"
        if any(e["scope"] in ("ES_ONLY_REPLACED", "EN_ONLY_REPLACED")
               for e in events)
        else "VARIANT_SCOPE_NOT_OBSERVABLE")

    out = {
        "gate": "G1-D VARIANT_LIFECYCLE_FALSIFICATION",
        "question": "Can a version_event affect only a subset of "
                    "submission_variant, or does a CNMV substitution always "
                    "replace the complete submission set?",
        "scope_vocabulary": SCOPE_VOCAB,
        "scan": {
            "filings_scanned": len(res2),
            "dual_variant_filings": duals,
            "filings_with_substitution_row": subs,
            "dual_plus_substitution": hits,
            "note": "substitution detection counts rows whose event label "
                    "contains 'sustitución'; TEF-20484's decisive event is "
                    "labelled 'otros', so label-based detection is a lower "
                    "bound only"},
        "candidates": candidates,
        "tef_20484": {
            "verdict_p1": tef["verdict_p1"],
            "nregaud": "20484", "nreg": tef["nreg"],
            "nreg_history": nreg_history,
            "events": events,
            "event_doc_bytes_equal_across_ui_langs": doc_pairs,
            "served_package_internal_zip_dates": {
                "es": next(d["zip_member_dt_distinct"]
                           for d in tef["phase1"]["es"]["docs"]
                           if d["kind"] == "ESEF_PACKAGE_ZIP"),
                "en": next(d["zip_member_dt_distinct"]
                           for d in tef["phase1"]["en"]["docs"]
                           if d["kind"] == "ESEF_PACKAGE_ZIP")}},
        "verdict": {
            "filing": filing_verdict,
            "events_with_variant_scope":
                [e["scope"] for e in events
                 if e["scope"] != "VARIANT_SCOPE_NOT_OBSERVABLE"],
            "model_implication":
                "A version_event affected only the -en submission_variant "
                "(official certificate: the published English version of the "
                "consolidated statements appeared in Spanish). Shared "
                "registry + shared event log, but per-variant artefact "
                "scope -> variant -> versions gains strong evidence.",
            "both_not_inferred":
                "No event is classified BOTH_VARIANTS_REPLACED merely "
                "because registry/dates are shared; the 28/02 event stays "
                "VARIANT_SCOPE_NOT_OBSERVABLE (reason scoped to individual "
                "accounts, silent on language)."}}
    (HERE / "g1d_results.json").write_bytes(
        json.dumps(out, indent=1, ensure_ascii=False).encode("utf-8"))
    print("filing verdict:", filing_verdict)
    for e in events:
        print(" ", e["event_date"], "->", e["scope"])
    print("candidates:", [(c["issuer"], c["verdict"]) for c in candidates])
    print("wrote g1d_results.json")


if __name__ == "__main__":
    main()
