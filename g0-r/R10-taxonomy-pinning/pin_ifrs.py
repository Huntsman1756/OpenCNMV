# R10 addendum: pin IFRS taxonomy files (transitive dependency of esef_cor) and
# the xbrl.org LEI module, both referenced by the pinned ESMA ESEF packages.
# The official IFRS taxonomy ZIP requires IFRS Foundation login (OAuth), so it
# cannot be fetched anonymously; instead we pin every canonical file served by
# https://xbrl.ifrs.org/ that the ESMA packages reference, transitively, then
# assemble local taxonomy packages (META-INF/catalog.xml rewriteURI, same
# mechanism ESMA uses) so Arelle resolves them offline.
import hashlib, io, json, re, sys, time, urllib.request, zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

BASE = Path(__file__).resolve().parent
EV = BASE / "evidence"
UA = {"User-Agent": "OpenCNMV-G0R-taxonomy-pinning (research; reproducible offline)"}

ESMA = {
    "2022-03-24": EV / "esef_taxonomy_2022_v1.1.zip",
    "2024-03-27": EV / "esef_taxonomy_2024.zip",
}
IFRS_HOST = "xbrl.ifrs.org"
LEI_PREFIX = "https://www.xbrl.org/taxonomy/int/lei/"
REF = re.compile(r'(?:schemaLocation|xlink:href|href)\s*=\s*"([^"]+)"')

def sha(b): return hashlib.sha256(b).hexdigest().upper()

def fetch(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if i == retries - 1: raise
            time.sleep(2 * (i + 1))

def urls_in(data):
    try:
        text = data.decode("utf-8", "replace")
    except Exception:
        return []
    return [m.group(1).split("#")[0].strip() for m in REF.finditer(text) if m.group(1).split("#")[0].strip()]

def package_refs(zpath):
    """Canonical URLs referenced anywhere in the ESMA package, keyed by host/prefix."""
    ifrs, lei = set(), set()
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if not n.endswith((".xsd", ".xml")): continue
            for u in urls_in(z.read(n)):
                pu = urlparse(u)
                if pu.netloc == IFRS_HOST: ifrs.add(u)
                elif u.startswith(LEI_PREFIX): lei.add(u)
    return ifrs, lei

def crawl(seeds, outdir, accept):
    """BFS over canonical URLs reachable from seeds. `accept(url)` filters scope."""
    done, queue, rows = set(), list(seeds), []
    while queue:
        url = queue.pop(0)
        if url in done or not accept(url): continue
        done.add(url)
        dest = outdir / urlparse(url).path.lstrip("/")
        if dest.exists():
            data = dest.read_bytes()
        else:
            data = fetch(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            time.sleep(0.25)
        rows.append({"url": url, "file": str(dest.relative_to(EV)).replace("\\", "/"),
                     "sha256": sha(data), "bytes": len(data)})
        for ref in urls_in(data):
            au = urljoin(url, ref)
            pau = urlparse(au)
            if pau.scheme == "http" and au not in done:
                au = "https" + au[4:]
            if au not in done and accept(au):
                queue.append(au)
    return rows

def build_pkg(root_name, rewrites, outdir, pkgpath, tp_id, tp_name):
    """Assemble a single-top-level-dir taxonomy package zip. `rewrites` maps
    canonical URL prefix -> internal package prefix (under root_name/)."""
    cat = ["<?xml version='1.0' encoding='UTF-8'?>",
           '<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">']
    for uri_prefix, internal in rewrites.items():
        cat.append(f'  <rewriteURI rewritePrefix="../{internal}" uriStartString="{uri_prefix}"/>')
        cat.append(f'  <rewriteURI rewritePrefix="../{internal}" uriStartString="{uri_prefix.replace("https://","http://")}"/>')
    cat.append("</catalog>")
    tp = ("<?xml version='1.0' encoding='UTF-8'?>\n"
          '<tp:taxonomyPackage xml:lang="en" xmlns:tp="http://xbrl.org/2016/taxonomy-package">\n'
          f"  <tp:identifier xml:lang=\"en\">{tp_id}</tp:identifier>\n"
          f"  <tp:name xml:lang=\"en\">{tp_name}</tp:name>\n"
          '  <tp:publisher xml:lang="en">Canonical files; package assembled by OpenCNMV R10</tp:publisher>\n'
          "</tp:taxonomyPackage>\n")
    with zipfile.ZipFile(pkgpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{root_name}/META-INF/catalog.xml", "\n".join(cat) + "\n")
        z.writestr(f"{root_name}/META-INF/taxonomyPackage.xml", tp)
        for uri_prefix, internal in rewrites.items():
            src = outdir / urlparse(uri_prefix).path.lstrip("/")
            if not src.exists(): continue
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    z.write(f, f"{root_name}/{internal}" + f.relative_to(src).as_posix())

def main():
    report = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "note": "IFRS taxonomy pinned as individual canonical files from xbrl.ifrs.org "
                      "(official ZIP requires IFRS Foundation login); LEI module pinned from "
                      "xbrl.org. Local taxonomy packages assembled for offline Arelle resolution.",
              "packages": []}
    lei_all = set()
    for version, zpath in ESMA.items():
        ifrs_seeds, lei = package_refs(zpath)
        lei_all |= lei
        outdir = EV / f"ifrs-taxonomy-{version}"
        print(f"{version}: {len(ifrs_seeds)} IFRS seed URLs, {len(lei)} LEI seed URLs")
        rows = crawl(sorted(ifrs_seeds), outdir, lambda u: urlparse(u).netloc == IFRS_HOST)
        pkg = EV / f"ifrs-full_ifrs-{version}-opencnmv-pkg.zip"
        build_pkg(f"ifrs_taxonomy_{version}",
                  {f"https://{IFRS_HOST}/taxonomy/{version}/": f"xbrl.ifrs.org/taxonomy/{version}/"},
                  outdir, pkg,
                  f"https://{IFRS_HOST}/taxonomy/{version}/full_ifrs-opencnmv-pinned",
                  f"IFRS full_ifrs {version} - pinned canonical files (OpenCNMV R10)")
        report["packages"].append({"package": f"ifrs-full_ifrs-{version}", "taxonomy_version": version,
                                   "files": len(rows), "members": rows,
                                   "package_file": pkg.name, "package_sha256": sha(pkg.read_bytes())})
        print(f"  crawled {len(rows)} files -> {pkg.name}")
    # LEI module (single version referenced by both ESMA packages)
    lei_ver = "2020-07-02"
    lei_outdir = EV / f"xbrl-lei-{lei_ver}"
    rows = crawl(sorted(lei_all), lei_outdir, lambda u: u.startswith(LEI_PREFIX))
    pkg = EV / f"xbrl-lei-{lei_ver}-opencnmv-pkg.zip"
    build_pkg(f"xbrl_lei_{lei_ver}",
              {f"https://www.xbrl.org/taxonomy/int/lei/{lei_ver}/": f"www.xbrl.org/taxonomy/int/lei/{lei_ver}/"},
              lei_outdir, pkg,
              f"https://www.xbrl.org/taxonomy/int/lei/{lei_ver}/opencnmv-pinned",
              f"XBRL LEI module {lei_ver} - pinned canonical files (OpenCNMV R10)")
    report["packages"].append({"package": f"xbrl-lei-{lei_ver}", "taxonomy_version": lei_ver,
                               "files": len(rows), "members": rows,
                               "package_file": pkg.name, "package_sha256": sha(pkg.read_bytes())})
    print(f"LEI: crawled {len(rows)} files -> {pkg.name}")
    (EV / "ifrs_pinning.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
