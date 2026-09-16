#!/usr/bin/env python3
"""R16 — ESEF_EXTERNAL_ORACLE_RECONCILIATION.

Compares the 6 corpus CNMV ESEF filings against filings.xbrl.org (oracle-only,
never authoritative). Reconciliation key: LEI + period_end + system=ESEF +
country=ES (CNMV source). Company names are diagnostic only.

Comparison levels (per user-specified ladder):
  L1  CNMV package sha256 == oracle package sha256
  L2  member paths + member sha256 (container repackaging tolerance)
  L3  iXBRL report member sha256
  L4  canonical fact multiset (oracle xBRL-JSON = Arelle projection =>
      labelled DATA_PROJECTION_CROSSCHECK, not an independent parser)

Verdict vocabulary (closed):
  EXACT_PACKAGE_MATCH | CONTENT_MATCH_CONTAINER_DIFF | SEMANTIC_MATCH_BYTES_DIFF
  ORACLE_OMISSION | MULTIPLE_ORACLE_CANDIDATES | OPEN_CNMV_POSSIBLE_OMISSION
  | UNEXPLAINED_DIVERGENCE

PASS = every observed difference reconciled or explicitly attributed.
"""
import hashlib
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
GATE = Path(__file__).resolve().parent
EV = GATE / "evidence"
DL = EV / "oracle_downloads"
R15 = ROOT / "g0-r" / "R15-offline-rebuild-deterministic" / "evidence" / "offlineA"
R7 = ROOT / "g0-r" / "R07-raw-retrieval" / "evidence"
R11 = ROOT / "g0-r" / "R11-esef-arelle-parse" / "evidence"

API = "https://filings.xbrl.org"
HDRS = {"Accept": "application/vnd.api+json", "User-Agent": "OpenCNMV-G0R-R16/1.0"}
LEIS = {
    "SAN": "5493006QMFDDMYWIAM13",
    "BBVA": "K8MS7FD7N5Z2WQ51AZ71",
    "IBE": "5QK37QC7NWOJ8D7WVQ45",
}
SLOT_PERIOD = {"FY2024": "2024-12-31", "FY2025": "2025-12-31"}

sys.path.insert(0, str(ROOT / "g0-r" / "R11-esef-arelle-parse"))
from r11_parse import oim_fact_key  # noqa: E402  (same normaliser as Control A)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest().upper()


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def get_json(url):
    r = requests.get(url, headers=HDRS, timeout=60)
    r.raise_for_status()
    return r.json()


def download(url, dest):
    r = requests.get(url, headers={"User-Agent": HDRS["User-Agent"]}, timeout=300)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return r.content


def member_manifest(zip_path):
    """path -> sha256 for every member of a ZIP (order-free)."""
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.endswith("/"):
                continue
            out[name] = sha256_bytes(z.read(name))
    return out


def ixbrl_members(manifest):
    """Report-member heuristic: .xhtml/.html/.htm members (iXBRL docs)."""
    return {k: v for k, v in manifest.items()
            if k.lower().endswith((".xhtml", ".html", ".htm"))}


def r16_oim_key(fact, nsmap, with_value=True):
    """Canonical key for an OIM xBRL-JSON fact (any producer). Same normaliser
    as Control A (oim_fact_key) + decimals + nil flag + value sha256."""
    base = oim_fact_key(fact, nsmap)
    d = fact.get("dimensions", {})
    v = fact.get("value")
    # Decimals placement: Arelle puts it inside `dimensions`, some OIM exports
    # at fact top level — read both.
    dec = fact.get("decimals", d.get("decimals", ""))
    key = "|".join([base, str(dec) if dec is not None else "",
                    "0" if v is not None else "1"])
    if with_value:
        key += "|" + (sha256_bytes(v.encode("utf-8")) if v is not None else "")
    return key


def oim_multiset(oim_bytes):
    """Fact multisets from an OIM xBRL-JSON document (oracle or ours).
    Returns (full_key multiset, semantic-only multiset, count, facts, nsmap)."""
    oim = json.loads(oim_bytes)
    nsmap = oim.get("documentInfo", {}).get("namespaces", {})
    facts = list(oim.get("facts", {}).values())
    return (Counter(r16_oim_key(fo, nsmap) for fo in facts),
            Counter(r16_oim_key(fo, nsmap, with_value=False) for fo in facts),
            len(facts), facts, nsmap)


def fact_multiset_cnmv_oim(issuer, slot):
    """Our committed R11 OIM export (same Arelle projection as the oracle's)."""
    import gzip
    return oim_multiset(
        gzip.open(R11 / f"{issuer}-{slot}.oim.json.gz", "rb").read())


def main():
    DL.mkdir(parents=True, exist_ok=True)
    corpus = [a for a in json.loads((R15 / "artifact_manifest.json")
                                    .read_text(encoding="utf-8-sig"))
              if a["artifact_role"] == "ESEF_PACKAGE_ZIP_XBRL"]

    # ---- 1. full LEI filing history (not just "first filing") ----------------
    entity_filings = {}
    for iss, lei in LEIS.items():
        d = get_json(f"{API}/api/entities/{lei}/filings?page[size]=200")
        entity_filings[iss] = d["data"]
        (EV / f"oracle_filings_{iss}.json").write_text(
            json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{iss}: {len(d['data'])} oracle filings (full LEI history)")

    # ---- 2. reconcile each corpus filing -------------------------------------
    matrix = []
    for c in sorted(corpus, key=lambda a: (a["issuer"], a["slot"])):
        iss, slot = c["issuer"], c["slot"]
        period_end = SLOT_PERIOD[slot]
        cnmv_zip = R7 / c["file"]
        cands = [f for f in entity_filings[iss]
                 if f["attributes"].get("period_end") == period_end
                 and f["attributes"].get("country") == "ES"
                 and "-ESEF-" in f["attributes"].get("fxo_id", "")]
        row = {
            "issuer": iss, "slot": slot, "period_end": period_end,
            "cnmv_registro": c["source_registration_no"], "lei": LEIS[iss],
            "cnmv_package_sha256": c["raw_sha256"],
            "oracle_candidates": [
                {"filing_id": f["id"], "fxo_id": f["attributes"]["fxo_id"],
                 "sha256": f["attributes"]["sha256"],
                 "date_added": f["attributes"]["date_added"],
                 "processed": f["attributes"]["processed"],
                 "package_url": f["attributes"]["package_url"],
                 "json_url": f["attributes"]["json_url"],
                 "error_count": f["attributes"]["error_count"],
                 "warning_count": f["attributes"]["warning_count"]}
                for f in cands],
            "comparisons": [], "verdict": None, "explanation": None,
        }
        print(f"\n== {iss}-{slot} reg {c['source_registration_no']} "
              f"-> {len(cands)} ES/ESEF oracle candidate(s)")

        if not cands:
            row["verdict"] = "ORACLE_OMISSION"
            row["explanation"] = ("No ES/ESEF filing for this LEI+period_end in "
                                  "oracle index; oracle docs explicitly state the "
                                  "index is not complete. CNMV remains authoritative.")
            matrix.append(row)
            continue

        cnmv_members = member_manifest(cnmv_zip)
        for f in cands:
            a = f["attributes"]
            fxo = a["fxo_id"]
            comp = {"fxo_id": fxo, "oracle_sha256_field": a["sha256"],
                    "package_url": a.get("package_url")}
            zip_dest = DL / f"{fxo}.zip"
            if not zip_dest.exists():
                print(f"  downloading {a['package_url']}")
                download(API + a["package_url"], zip_dest)
            comp["package_sha256_actual"] = sha256_file(zip_dest)
            comp["package_sha_matches_api"] = (
                comp["package_sha256_actual"].lower() == a["sha256"].lower())
            comp["package_byte_equal"] = (
                comp["package_sha256_actual"] == c["raw_sha256"])
            oracle_members = member_manifest(zip_dest)
            comp["member_count_cnmv"] = len(cnmv_members)
            comp["member_count_oracle"] = len(oracle_members)
            shared = set(cnmv_members) & set(oracle_members)
            comp["members_equal"] = (
                set(cnmv_members) == set(oracle_members)
                and all(cnmv_members[k] == oracle_members[k] for k in shared))
            comp["member_path_overlap"] = len(shared)
            comp["members_same_content"] = (
                bool(shared) and all(
                    cnmv_members[k] == oracle_members[k] for k in shared))
            ix_c, ix_o = ixbrl_members(cnmv_members), ixbrl_members(oracle_members)
            comp["ixbrl_members_cnmv"] = len(ix_c)
            comp["ixbrl_members_oracle"] = len(ix_o)
            comp["ixbrl_sha_overlap"] = sorted(set(ix_c.values()) & set(ix_o.values()))
            comp["ixbrl_equal_any"] = bool(comp["ixbrl_sha_overlap"])

            # L4: fact multiset — oracle OIM vs our committed R11 OIM.
            # Both are Arelle projections => DATA_PROJECTION_CROSSCHECK.
            if a.get("json_url"):
                jdest = DL / f"{fxo}.json"
                if not jdest.exists():
                    print(f"  downloading {a['json_url']}")
                    download(API + a["json_url"], jdest)
                comp["oim_json_sha256"] = sha256_file(jdest)
                try:
                    o_ms, o_ms_nv, o_n, oim_facts_o, oim_ns_o = \
                        oim_multiset(jdest.read_bytes())
                    c_ms, c_ms_nv, c_n, oim_facts_c, oim_ns_c = \
                        fact_multiset_cnmv_oim(iss, slot)
                    comp["fact_count_oracle"] = o_n
                    comp["fact_count_cnmv"] = c_n
                    comp["fact_multiset_equal"] = (o_ms == c_ms)
                    comp["facts_only_in_oracle"] = sum((o_ms - c_ms).values())
                    comp["facts_only_in_cnmv"] = sum((c_ms - o_ms).values())
                    # Diagnostic: semantic-key diff ignoring the value hash
                    # isolates lexical-value vs structural differences.
                    comp["semantic_keys_only_in_oracle"] = sum(
                        (o_ms_nv - c_ms_nv).values())
                    comp["semantic_keys_only_in_cnmv"] = sum(
                        (c_ms_nv - o_ms_nv).values())
                    # Numeric cores: language-variant packages translate the
                    # extension taxonomy (concept/member names es<->en; SAN even
                    # changes namespace santanderbank.com->santander.com), so the
                    # language-independent signal is facts on shared-taxonomy
                    # concepts carrying a unit.
                    def num_ms(ms):
                        return Counter(k for k in ms
                                       if "|" in k and k.split("|")[7])
                    num_o, num_c = num_ms(o_ms_nv), num_ms(c_ms_nv)
                    comp["numeric_facts_oracle"] = sum(num_o.values())
                    comp["numeric_facts_cnmv"] = sum(num_c.values())
                    comp["numeric_facts_shared"] = sum((num_o & num_c).values())
                    # Stricter: undimensioned numeric facts on ifrs-full
                    # concepts — insensitive to translated extension members.
                    def ifrs_undim(facts, ns):
                        return Counter(
                            r16_oim_key(f, ns, with_value=False) for f in facts
                            if f["dimensions"].get("unit")
                            and f["dimensions"].get("concept", "")
                                .startswith(("ifrs-full:", "ifrs:"))
                            and not any(
                                x not in ("concept", "entity", "period", "unit",
                                          "language", "noteId", "decimals")
                                for x in f["dimensions"]))
                    io_ms = ifrs_undim(oim_facts_o, oim_ns_o)
                    ic_ms = ifrs_undim(oim_facts_c, oim_ns_c)
                    comp["ifrs_undim_numeric_oracle"] = sum(io_ms.values())
                    comp["ifrs_undim_numeric_cnmv"] = sum(ic_ms.values())
                    comp["ifrs_undim_numeric_shared"] = sum(
                        (io_ms & ic_ms).values())
                    # Facts with identical semantic key but different value
                    # hash -> candidate real content divergences.
                    vdiff = []
                    o_full = Counter(r16_oim_key(fo, oim_ns_o)
                                     for fo in oim_facts_o)
                    c_full = Counter(r16_oim_key(fc, oim_ns_c)
                                     for fc in oim_facts_c)
                    for k in (o_ms_nv & c_ms_nv):
                        o_vs = {fk.rsplit("|", 1)[-1]
                                for fk in o_full if fk.startswith(k + "|")}
                        c_vs = {fk.rsplit("|", 1)[-1]
                                for fk in c_full if fk.startswith(k + "|")}
                        if o_vs != c_vs:
                            ov = next((f["value"] for f in oim_facts_o
                                       if r16_oim_key(f, oim_ns_o,
                                                      with_value=False) == k),
                                      None)
                            cv = next((f["value"] for f in oim_facts_c
                                       if r16_oim_key(f, oim_ns_c,
                                                      with_value=False) == k),
                                      None)
                            vdiff.append({"semantic_key": k[:400],
                                          "oracle_value": str(ov)[:200],
                                          "cnmv_value": str(cv)[:200],
                                          "oracle_value_shas": sorted(o_vs),
                                          "cnmv_value_shas": sorted(c_vs)})
                    comp["same_key_diff_value"] = vdiff
                except Exception as e:  # noqa: BLE001
                    comp["fact_multiset_error"] = f"{type(e).__name__}: {e}"
            row["comparisons"].append(comp)
            print(f"  {fxo}: pkg_eq={comp['package_byte_equal']} "
                  f"members_eq={comp['members_equal']} "
                  f"ixbrl_overlap={len(comp['ixbrl_sha_overlap'])} "
                  f"facts_eq={comp.get('fact_multiset_equal')}")

        # ---- verdict ---------------------------------------------------------
        if any(c.get("package_byte_equal") for c in row["comparisons"]):
            row["verdict"] = "EXACT_PACKAGE_MATCH"
        elif len(cands) > 1 and not any(
                c.get("package_byte_equal") or c.get("members_equal")
                or c.get("ixbrl_equal_any") for c in row["comparisons"]):
            row["verdict"] = "MULTIPLE_ORACLE_CANDIDATES"
        elif any(c.get("members_equal") for c in row["comparisons"]):
            row["verdict"] = "CONTENT_MATCH_CONTAINER_DIFF"
        elif any(c.get("ixbrl_equal_any") or c.get("fact_multiset_equal")
                 for c in row["comparisons"]):
            row["verdict"] = "SEMANTIC_MATCH_BYTES_DIFF"
        elif any(
            # Language-variant parallel submission: the oracle package carries
            # a different language tag (-en vs our -es) for the same
            # LEI+period, and a substantial shared language-independent
            # numeric core proves it is the same underlying report — a CNMV
            # OAM submission our ListadoIFA surface does not expose.
            c.get("package_url", "").rsplit("/", 1)[-1].lower()
                .endswith("-en.zip")
            and (c.get("ifrs_undim_numeric_shared") or 0) > 0.3 * min(
                c.get("ifrs_undim_numeric_oracle") or 0,
                c.get("ifrs_undim_numeric_cnmv") or 0)
            for c in row["comparisons"]):
            row["verdict"] = "OPEN_CNMV_POSSIBLE_OMISSION"
            c0 = row["comparisons"][0]
            row["explanation"] = (
                "Oracle indexes a parallel language-variant ESEF submission "
                f"({c0['fxo_id']}, package "
                f"'{(c0.get('package_url') or '').rsplit('/', 1)[-1]}') for the "
                "same LEI+period. CNMV ListadoIFA exposes one ZIP per registro "
                "(the -es package we hold); the -en package is a distinct OAM "
                "submission not surfaced there. Shared ifrs-full undimensioned "
                "numeric core: "
                f"{c0.get('ifrs_undim_numeric_shared')}/"
                f"{c0.get('ifrs_undim_numeric_cnmv')} facts identical; "
                "extension concepts/members are language-parallel "
                "(SAN also changes extension namespace). "
                f"same-key value diffs: {len(c0.get('same_key_diff_value', []))}"
                " (see comparisons[].same_key_diff_value).")
        else:
            row["verdict"] = "UNEXPLAINED_DIVERGENCE"
        matrix.append(row)

    # ---- 3. cross-authority diagnostic: SAN GB filings ------------------------
    # The oracle indexes the same issuer's FCA submissions. If a GB package
    # carries the same iXBRL bytes as a CNMV package, the oracle *has* the
    # content and the ES omission is pure indexing lag.
    diag = []
    for f in entity_filings["SAN"]:
        a = f["attributes"]
        if a.get("country") != "GB" or a.get("period_end") not in ("2024-12-31", "2025-12-31"):
            continue
        fxo = a["fxo_id"]
        if not a.get("package_url"):
            continue
        zip_dest = DL / f"{fxo}.zip"
        if not zip_dest.exists():
            print(f"diagnostic download {fxo}")
            download(API + a["package_url"], zip_dest)
        om = member_manifest(zip_dest)
        d = {"fxo_id": fxo, "package_sha256_actual": sha256_file(zip_dest),
             "ixbrl_shas": sorted(ixbrl_members(om).values()),
             "member_count": len(om)}
        for c in corpus:
            if c["issuer"] == "SAN" and SLOT_PERIOD[c["slot"]] == a["period_end"]:
                cm = member_manifest(R7 / c["file"])
                d["cnmv_slot"] = c["slot"]
                d["cnmv_ixbrl_shas"] = sorted(ixbrl_members(cm).values())
                d["ixbrl_shared_with_cnmv"] = bool(
                    set(d["ixbrl_shas"]) & set(d["cnmv_ixbrl_shas"]))
                d["members_shared_with_cnmv"] = len(set(om) & set(cm))
        diag.append(d)
        print("diag", fxo, d)

    out = {
        "gate": "R16", "executed_utc": __import__("datetime").datetime
            .utcnow().isoformat() + "Z",
        "oracle": "filings.xbrl.org (JSON:API; xBRL-JSON generated by Arelle => "
                  "DATA_PROJECTION_CROSSCHECK, not an independent parser)",
        "reconciliation_key": "LEI + period_end + system=ESEF + country=ES (CNMV source)",
        "cnmv_target_filings": len(corpus),
        "matrix": matrix,
        "cross_authority_diagnostic": diag,
    }
    (EV / "reconciliation.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    verdicts = Counter(r["verdict"] for r in matrix)
    print("\n=== verdicts:", dict(verdicts))
    unexplained = [r for r in matrix if r["verdict"] == "UNEXPLAINED_DIVERGENCE"]
    omissions = [r for r in matrix if r["verdict"] == "OPEN_CNMV_POSSIBLE_OMISSION"]
    print("unexplained:", len(unexplained), "| opencnmv omissions:", len(omissions))
    # Gate contract: "explain or open every divergence as a finding". An
    # attributed OPEN_CNMV_POSSIBLE_OMISSION is an opened finding, not an
    # unexplained divergence — it feeds the final G0-R verdict as a coverage
    # caveat (parallel -en submissions exist on the OAM feed but are not
    # exposed via ListadoIFA, our discovery surface).
    print("R16 =", "PASS" if not unexplained else "FAIL",
          "(findings opened:", len(omissions), "coverage caveats)")


if __name__ == "__main__":
    main()
