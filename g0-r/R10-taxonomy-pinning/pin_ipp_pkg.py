# R10 addendum (discovered by R12): assemble a local taxonomy package for the
# CNMV IPP 2019-01-01 taxonomy. The pinned artefact cnmv-ipp_2019-01-01.zip is a
# flat ZIP of XSD/linkbase files (no META-INF), so Arelle cannot load it via
# `packages`. This script re-wraps the same bytes under their canonical URL
# paths plus META-INF/catalog.xml rewriteURI (same mechanism used for the
# IFRS/LEI packages, which is the same mechanism ESMA uses), so IPP instances
# resolve http://www.cnmv.es/xbrl/ipp/... offline from pinned bytes.
#
# xbrl.org base schemas (xbrl-instance/linkbase/xl/xlink/xbrldt/xbrldi/DTR) are
# bundled from the R10-pinned loose files so the whole DTS resolves from pinned
# inputs (not from Arelle's per-user web cache, which would be an unpinned
# machine-local dependency).
import hashlib, json, zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
EV = BASE / "evidence"
SRC = EV / "cnmv-ipp_2019-01-01.zip"
OUT = EV / "cnmv-ipp-2019-01-01-opencnmv-pkg.zip"

def sha(b): return hashlib.sha256(b).hexdigest().upper()

# Canonical URL path each taxonomy family is published under. Only /en/ and /ge/
# are exercised by the frozen corpus (R9); /se/ and /ti/ are mapped by analogy
# with the observed schemaRef pattern and are not exercised.
FAM = {
    "ipp_en": "ipp/en/2019-01-01/",
    "ipp_ge": "ipp/ge/2019-01-01/",
    "ipp_se": "ipp/se/2019-01-01/",
    "ipp_ti": "ipp/ti/2019-01-01/",
}

CAT = "\n".join([
    "<?xml version='1.0' encoding='UTF-8'?>",
    '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">',
    '  <rewriteURI rewritePrefix="../ipp/" uriStartString="http://www.cnmv.es/xbrl/ipp/"/>',
    '  <rewriteURI rewritePrefix="../ipp/" uriStartString="https://www.cnmv.es/xbrl/ipp/"/>',
    '  <rewriteURI rewritePrefix="../www.xbrl.org/" uriStartString="http://www.xbrl.org/"/>',
    '  <rewriteURI rewritePrefix="../www.xbrl.org/" uriStartString="https://www.xbrl.org/"/>',
    "</catalog>",
]) + "\n"

TP = ("<?xml version='1.0' encoding='UTF-8'?>\n"
      '<tp:taxonomyPackage xml:lang="en" xmlns:tp="http://xbrl.org/2016/taxonomy-package">\n'
      '  <tp:identifier xml:lang="en">http://www.cnmv.es/xbrl/ipp/2019-01-01/opencnmv-pinned</tp:identifier>\n'
      '  <tp:name xml:lang="en">CNMV IPP 2019-01-01 - pinned canonical files (OpenCNMV R10)</tp:name>\n'
      '  <tp:publisher xml:lang="en">Canonical CNMV files; package assembled by OpenCNMV R10</tp:publisher>\n'
      "</tp:taxonomyPackage>\n")

def main():
    members = []
    with zipfile.ZipFile(SRC) as zin, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("cnmv_ipp_2019-01-01/META-INF/catalog.xml", CAT)
        z.writestr("cnmv_ipp_2019-01-01/META-INF/taxonomyPackage.xml", TP)
        for n in sorted(zin.namelist()):
            data = zin.read(n)
            if n.endswith(".xbrl"):
                dest = "samples/" + n        # CNMV sample instances: preserved, not rewritten
            else:
                dest = next((v for k, v in FAM.items() if n.startswith(k)), "misc/") + n
            z.writestr("cnmv_ipp_2019-01-01/" + dest, data)
            members.append({"member": dest, "source_member": n,
                            "sha256": sha(data), "bytes": len(data)})
        # pinned xbrl.org base schemas -> canonical path layout
        for f in sorted(EV.glob("xbrlorg_www.xbrl.org_*")):
            rel = f.name[len("xbrlorg_www.xbrl.org_"):]
            dest = "www.xbrl.org/" + "/".join(rel.split("_"))
            data = f.read_bytes()
            z.writestr("cnmv_ipp_2019-01-01/" + dest, data)
            members.append({"member": dest, "source_member": f.name,
                            "sha256": sha(data), "bytes": len(data)})
    report = {
        "package": "cnmv-ipp-2019-01-01-opencnmv-pkg",
        "source_zip": SRC.name,
        "source_zip_sha256": sha(SRC.read_bytes()),
        "package_file": OUT.name,
        "package_sha256": sha(OUT.read_bytes()),
        "rewrites": {"http://www.cnmv.es/xbrl/ipp/": "ipp/ (canonical layout)",
                     "http://www.xbrl.org/": "www.xbrl.org/ (R10-pinned base schemas)"},
        "members": members,
    }
    (EV / "ipp_pkg_members.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {OUT.name} sha256={report['package_sha256']} members={len(members)}")

if __name__ == "__main__":
    main()
