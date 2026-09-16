# G1-D verifier — deterministic checks over preserved evidence.
# Rebuilds g1d_results.json from evidence and compares bytes; re-extracts
# PDF text to prove extraction determinism; asserts the scope verdicts.
from __future__ import annotations

import hashlib, io, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE / "evidence"

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append({"check": name, "status": "PASS" if ok else "FAIL",
                   "detail": detail})
    print(("PASS " if ok else "FAIL "), name, ("| " + detail) if detail else "")
    return ok


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def main():
    tef = json.loads((HERE / "g1d_tef20484.json").read_text(encoding="utf-8"))
    res = json.loads((HERE / "g1d_results.json").read_text(encoding="utf-8"))
    man = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))

    # 1. TEF-20484 is a real dual-variant filing
    es_pkg = next(d for d in tef["phase1"]["es"]["docs"]
                  if d["kind"] == "ESEF_PACKAGE_ZIP")
    en_pkg = next(d for d in tef["phase1"]["en"]["docs"]
                  if d["kind"] == "ESEF_PACKAGE_ZIP")
    check("tef20484_dual_variant",
          tef["verdict_p1"] == "DUAL_VARIANT_SHARED_REGISTRY"
          and tef["submitted_variant_count"] == 2
          and es_pkg["package_lang_tag"] == "es"
          and en_pkg["package_lang_tag"] == "en"
          and es_pkg["sha256"] != en_pkg["sha256"],
          f"es={es_pkg['sha256'][:12]} en={en_pkg['sha256'][:12]}")

    # 2. packages preserved on disk with matching sha256
    pkg_ok = all(
        (EV / f"pkg-TEF-20484-{l}-{p['sha256'][:12]}.zip").exists()
        and sha256((EV / f"pkg-TEF-20484-{l}-{p['sha256'][:12]}.zip")
                   .read_bytes()) == p["sha256"]
        for l, p in (("es", es_pkg), ("en", en_pkg)))
    check("variant_packages_preserved", pkg_ok)

    # 3. EN_ONLY event: the decisive clause is present in preserved text
    e1_txt = (EV / "doc-TEF-20484-es-e1-0.txt").read_text(encoding="utf-8")
    e1_norm = re.sub(r"\s+", " ", e1_txt)
    decisive = ("versión en inglés publicada" in e1_norm
                and "aparece en español" in e1_norm)
    ev_en = next(e for e in res["tef_20484"]["events"]
                 if e["event_date"] == "2025-03-13")
    check("en_only_replaced_event",
          decisive and ev_en["scope"] == "EN_ONLY_REPLACED",
          ev_en["reason_clause"][:110] if ev_en["reason_clause"] else "")

    # 4. 28/02 event: no language scope in reason -> NOT_OBSERVABLE
    ev_feb = next(e for e in res["tef_20484"]["events"]
                  if e["event_date"] == "2025-02-28")
    check("feb_event_scope_not_observable",
          ev_feb["scope"] == "VARIANT_SCOPE_NOT_OBSERVABLE"
          and ev_feb["reason_clause"] is not None
          and "Cuentas Anuales Individuales" in ev_feb["reason_clause"]
          and not re.search(r"versi[oó]n en (ingl[eé]s|espa[nñ]ol)",
                            ev_feb["reason_clause"], re.I),
          (ev_feb["reason_clause"] or "")[:110])

    # 5. shared event history: same cert bytes under both UI languages
    pairs = tef["phase3"]["event_doc_bytes_equal_es_vs_en"]
    check("shared_event_history_same_docs",
          len(pairs) == 3 and all(pairs.values()),
          "es/en views serve byte-identical certificates")

    # 6. scope vocabulary + BOTH not inferred
    vocab = set(res["scope_vocabulary"])
    scopes = {e["scope"] for e in res["tef_20484"]["events"]}
    check("scope_vocabulary_and_no_inferred_both",
          vocab == {"BOTH_VARIANTS_REPLACED", "ES_ONLY_REPLACED",
                    "EN_ONLY_REPLACED", "VARIANT_SCOPE_NOT_OBSERVABLE"}
          and scopes <= vocab
          and "BOTH_VARIANTS_REPLACED" not in scopes,
          f"scopes={sorted(scopes)}")

    # 7. filing-level verdict
    check("filing_verdict_independent_lifecycle",
          res["verdict"]["filing"] == "INDEPENDENT_VARIANT_LIFECYCLE_PROVEN")

    # 8. other substitution candidates cannot falsify (not dual-variant)
    others = [c for c in res["candidates"]
              if c["issuer"] != "TELEFONICA"]
    check("other_candidates_not_dual",
          all(c["verdict"] == "SINGLE_VARIANT_WITH_UI_FALLBACK"
              and c["can_falsify"] is False for c in others),
          str([(c["issuer"], c["verdict"]) for c in others]))

    # 9. PDF text extraction deterministic (re-extract == preserved .txt)
    try:
        from pypdf import PdfReader
        ok9 = True
        for n in ("e1", "e2", "e3"):
            pdf = EV / f"doc-TEF-20484-es-{n}-0.pdf"
            txt = EV / f"doc-TEF-20484-es-{n}-0.txt"
            re_txt = "\n".join(
                (p.extract_text() or "")
                for p in PdfReader(io.BytesIO(pdf.read_bytes())).pages)
            if re_txt != txt.read_text(encoding="utf-8"):
                ok9 = False
        check("pdf_text_extraction_deterministic", ok9)
    except Exception as ex:  # noqa: BLE001
        check("pdf_text_extraction_deterministic", False, str(ex))

    # 10. results dataset deterministic (rebuild -> byte-identical)
    before = (HERE / "g1d_results.json").read_bytes()
    subprocess.run([sys.executable, "-X", "utf8",
                    str(HERE / "g1d_results.py")],
                   check=True, capture_output=True)
    check("results_dataset_deterministic",
          (HERE / "g1d_results.json").read_bytes() == before)

    # 11. every manifest artifact exists with matching sha256
    missing = []
    for a in man.get("artifacts", []):
        f = a["file"]
        p = (HERE / f) if not f.startswith("evidence/") else EV / f[9:]
        if f.startswith("evidence/"):
            p = EV / f[len("evidence/"):]
        else:
            p = HERE / f
        if not p.exists() or sha256(p.read_bytes()) != a["sha256"]:
            missing.append(f)
    check("manifest_artifacts_preserved", not missing,
          f"missing/mismatch: {missing}" if missing else
          f"{len(man.get('artifacts', []))} artifacts ok")

    n_pass = sum(1 for c in CHECKS if c["status"] == "PASS")
    verdict = "PASS" if n_pass == len(CHECKS) else "FAIL"
    print(f"\nG1-D: {verdict} ({n_pass}/{len(CHECKS)})")
    (HERE / "g1d_verify_results.json").write_bytes(json.dumps(
        {"verdict": verdict, "checks": CHECKS},
        indent=1, ensure_ascii=False).encode("utf-8"))
    return verdict == "PASS"


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
