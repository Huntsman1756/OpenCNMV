# R11 Control B - Arelle vs Brel (independent second oracle) on SAN FY2025.
# Brel runs in the isolated .venv-brel environment. Its URL cache is pre-seeded
# with the same pinned bytes Arelle resolves (issuer extension from the report
# package, ESMA/IFRS/LEI/xbrl.org from R10 evidence), so the oracle reads
# identical inputs offline. Structural invariants only - no byte comparison.
import json, os, sys, tempfile, zipfile
from collections import Counter
from pathlib import Path

import brel
from brel.characteristics import (ExplicitDimensionCharacteristic,
                                  TypedDimensionCharacteristic)

REPO = Path(__file__).resolve().parents[2]
EV = Path(__file__).resolve().parent / "evidence"
R10EV = REPO / "g0-r/R10-taxonomy-pinning/evidence"
PKG = REPO / "g0-r/R07-raw-retrieval/evidence/esef-SAN-FY2025-package.zip"
REPORT_MEMBER = "5493006QMFDDMYWIAM13-2025-12-31-1-es/reports/5493006QMFDDMYWIAM13-2025-12-31-1-es.xhtml"
CACHE = Path.home() / ".brel" / "dts_cache"

def brel_filename(uri: str) -> str:
    fmt = uri.split(".")[-1]
    u = uri[: -(len(fmt) + 1)]
    u = u.replace("http://", "").replace("https://", "").replace("www.", "")
    for ch in "/:?.":
        u = u.replace(ch, "_")
    return u.replace("\\", "_") + "." + fmt

def seed(cache_file: Path, data: bytes):
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(data)

def seed_dts_cache():
    n = 0
    with zipfile.ZipFile(PKG) as z:
        for m in z.namelist():
            parts = m.split("/")
            if len(parts) >= 3 and parts[-1] and "." in parts[1] and parts[1] != "META-INF" \
                    and parts[-1].rsplit(".", 1)[-1] in ("xml", "xsd", "htm", "html"):
                seed(CACHE / brel_filename(f"https://{parts[1]}/" + "/".join(parts[2:])), z.read(m)); n += 1
    with zipfile.ZipFile(R10EV / "esef_taxonomy_2024.zip") as z:
        for m in z.namelist():
            parts = m.split("/")
            if len(parts) >= 3 and parts[-1] and parts[1].endswith("europa.eu") \
                    and parts[-1].rsplit(".", 1)[-1] in ("xml", "xsd", "htm", "html"):
                seed(CACHE / brel_filename(f"https://{parts[1]}/" + "/".join(parts[2:])), z.read(m)); n += 1
    base = R10EV / "ifrs-taxonomy-2024-03-27" / "taxonomy" / "2024-03-27"
    for f in base.rglob("*"):
        if f.is_file():
            seed(CACHE / brel_filename(f"https://xbrl.ifrs.org/taxonomy/2024-03-27/" + f.relative_to(base).as_posix()),
                 f.read_bytes()); n += 1
    lei = R10EV / "xbrl-lei-2020-07-02" / "taxonomy" / "int" / "lei" / "2020-07-02"
    for f in lei.rglob("*"):
        if f.is_file():
            seed(CACHE / brel_filename(f"https://www.xbrl.org/taxonomy/int/lei/2020-07-02/" + f.relative_to(lei).as_posix()),
                 f.read_bytes()); n += 1
    man = json.loads((REPO / "g0-r/R10-taxonomy-pinning/taxonomy_manifest.json").read_text(encoding="utf-8-sig"))
    rows = man["rows"] if isinstance(man, dict) and "rows" in man else man
    for r in rows:
        if str(r.get("package", "")).startswith("xbrl.org:"):
            fp = R10EV / r["file"] if "file" in r else None
            if fp and fp.exists():
                seed(CACHE / brel_filename(r["source_url"]), fp.read_bytes()); n += 1
    print(f"seeded {n} files into {CACHE}")

def qn_str(q):
    """Normalise a brel QName to `ns#local` matching the Arelle side."""
    try:
        return f"{q.get_URL()}#{q.get_local_name()}"
    except Exception:
        return str(q)

def fact_sig_brel(f):
    """Context signature from a brel fact, same field layout as Arelle side."""
    ent, per, dims = "", "", []
    try:
        e = f.get_entity()
        ent = f"{e.get_schema()}:{e.get_value()}"
    except Exception:
        pass
    try:
        p = f.get_period()
        per = (str(p.get_instant_period().date()) if p.is_instant()
               else f"{p.get_start_period().date()}/{p.get_end_period().date()}")
    except Exception:
        per = str(f.get_period())
    try:
        for a in f.get_context().get_aspects():
            if a.is_core():
                continue
            ch = f.get_context().get_characteristic(a)
            if isinstance(ch, ExplicitDimensionCharacteristic):
                dims.append("E:" + qn_str(ch.get_dimension()) + "=" + qn_str(ch.get_member()))
            elif isinstance(ch, TypedDimensionCharacteristic):
                dims.append("T:" + qn_str(ch.get_dimension()) + "=" + str(ch.get_value()))
    except Exception:
        pass
    return ent, per, ";".join(sorted(dims))

def main():
    seed_dts_cache()
    tmp = Path(tempfile.mkdtemp(prefix="r11_brel_"))
    with zipfile.ZipFile(PKG) as z:
        z.extractall(tmp)
    member = tmp / REPORT_MEMBER
    report = member.with_suffix(".html")   # brel xhtml mode accepts .xml/.htm/.html only
    member.rename(report)
    print("opening", report, flush=True)
    filing = brel.Filing.open(str(report), mode="xhtml")
    facts = filing.get_all_facts()

    brel_concepts = Counter()
    ctx_keys = set()
    facts_with_dims = 0
    for f in facts:
        try:
            brel_concepts[qn_str(f.get_concept().get_value().get_name())] += 1
        except Exception:
            brel_concepts[str(f.get_concept())] += 1
        ent, per, dim_s = fact_sig_brel(f)
        if dim_s:
            facts_with_dims += 1
        ctx_keys.add(f"{ent}|{per}|{dim_s}")

    # Arelle side for comparison (same normalisation)
    arelle_facts = [json.loads(l) for l in
                    open(EV / "SAN-FY2025.facts.jsonl", encoding="utf-8")]
    arelle_concepts = Counter(r["concept"] for r in arelle_facts)
    arelle_ctx = set()
    for r in arelle_facts:
        per = (r.get("period_instant") or
               f"{r.get('period_start','')}/{r.get('period_end','')}")
        dims = ";".join(f"{k}={v}" for k, v in sorted(r.get("dimensions", {}).items()))
        arelle_ctx.add(f"{r.get('entity_scheme','')}:{r.get('entity','')}|{per}|{dims}")

    only_a = arelle_concepts - brel_concepts
    only_b = brel_concepts - arelle_concepts
    common = arelle_concepts & brel_concepts
    res = {
        "filing": "SAN-FY2025",
        "engine": "brel-xbrl 0.8.2a1",
        "brel": {
            "fact_count": len(facts),
            "distinct_context_signatures": len(ctx_keys),
            "concept_count_reported": len(brel_concepts),
            "facts_with_dimensions": facts_with_dims,
        },
        "arelle": {
            "fact_count": len(arelle_facts),
            "distinct_context_signatures": len(arelle_ctx),
            "concept_count_reported": len(arelle_concepts),
            "facts_with_dimensions": sum(1 for r in arelle_facts if r.get("dimensions")),
        },
        "concept_coverage": {
            "concepts_common": len(common),
            "concepts_only_arelle": len(only_a),
            "concepts_only_brel": len(only_b),
            "only_arelle_sample": sorted(only_a)[:20],
            "only_brel_sample": sorted(only_b)[:20],
            "per_concept_count_diffs_sample": [
                f"{c}: arelle={arelle_concepts[c]} brel={brel_concepts[c]}"
                for c in common if arelle_concepts[c] != brel_concepts[c]][:20],
        },
    }
    (EV / "control_b_brel.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
