"""G2-G wheel step (B14): build the wheel, install into a clean venv,
then bootstrap a dataset from an EMPTY working directory with fully
external inputs — a preserved-evidence subset and a taxonomy bundle
copied out of the checkout. Nothing resolves from g0-r/, g1/, g2/ or
_out/ at runtime.

    python g2g_wheel.py

Produces _out/wheel_smoke_g.json.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import g2g_common as C  # noqa: E402

# the bounded evidence subset: G2-F's dedup-probe run (IBE/IPP, 11
# preserved artifacts) + the IPP taxonomy package — enough to prove the
# evidence->assemble->bootstrap path through the installed wheel.
PROBE_RUN = "cap-202609172201420000"
DEPS = ["pydantic==2.13.4", "requests==2.33.0", "duckdb==1.5.5",
        "pyarrow==25.0.1", "jsonschema==4.26.0",
        "arelle-release==2.44.0", "pypdf==6.14.2"]


def _venv_python(env: Path) -> Path:
    s = env / ("Scripts" if sys.platform == "win32" else "bin")
    return s / ("python.exe" if sys.platform == "win32" else "python")


def _evidence_paths(o, out: set) -> None:
    if isinstance(o, dict):
        if "evidence_path" in o:
            out.add(o["evidence_path"])
        for v in o.values():
            _evidence_paths(v, out)
    elif isinstance(o, list):
        for v in o:
            _evidence_paths(v, out)


def stage_external_inputs(root: Path) -> tuple[Path, Path]:
    """Copy the probe-run evidence subset + IPP taxonomy into ``root``
    — fully external, no repo path survives."""
    ev = root / "evidence"
    tax = root / "taxonomy"
    man = C.jload(C.EV_A / "runs" / PROBE_RUN / "manifest.json")
    (ev / "runs" / PROBE_RUN).mkdir(parents=True)
    C.jwrite(ev / "runs" / PROBE_RUN / "manifest.json", man)
    paths: set = set()
    _evidence_paths(man, paths)
    for rel in paths:
        dst = ev / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(C.EV_A / rel, dst)
    tax.mkdir(parents=True)
    shutil.copy2(C.TAX_DIR / "cnmv-ipp-2019-01-01-opencnmv-pkg.zip", tax)
    return ev, tax


def main() -> int:
    dist = REPO / "dist"
    subprocess.run([sys.executable, "-m", "build", "--no-isolation"],
                   cwd=REPO, check=True)
    wheel = sorted(dist.glob("opencnmv-*.whl"))[-1]

    env = C.OUT / "wheelenv_g"
    if env.exists():
        shutil.rmtree(env)
    venv.create(env, with_pip=True)
    py = _venv_python(env)
    subprocess.run([str(py), "-m", "pip", "install", *DEPS],
                   check=True)
    subprocess.run([str(py), "-m", "pip", "install", "--no-deps",
                    str(wheel)], check=True)
    chk = subprocess.run([str(py), "-m", "pip", "check"],
                         capture_output=True, text=True)
    if chk.returncode != 0:
        print(chk.stdout + chk.stderr)
        return 1
    exe = env / ("Scripts" if sys.platform == "win32" else "bin")
    exe = exe / ("opencnmv.exe" if sys.platform == "win32" else "opencnmv")

    results = []
    with tempfile.TemporaryDirectory(prefix="g2g_wheel_") as td:
        work = Path(td)
        ev, tax = stage_external_inputs(work / "inputs")
        cwd = work / "empty_cwd"          # empty working dir, no checkout
        cwd.mkdir()

        def run(argv):
            r = subprocess.run([str(exe), *argv], cwd=cwd,
                               capture_output=True)
            return {"argv": argv,
                    "exit": r.returncode,
                    "stdout": r.stdout.decode("utf-8",
                                              errors="replace")[-600:],
                    "stderr": r.stderr.decode("utf-8",
                                              errors="replace")[-600:]}

        ds = work / "ds"
        ds2 = work / "ds2"
        results.append(("init_evidence", run(
            ["init", "--dataset", str(ds),
             "--evidence-dir", str(ev), "--taxonomy-dir", str(tax),
             "--run", PROBE_RUN]), 0))
        results.append(("validate", run(
            ["dataset", "validate", "--dataset", str(ds)]), 0))
        results.append(("filings", run(
            ["filings", "--dataset", str(ds)]), 0))
        results.append(("init_second", run(
            ["init", "--dataset", str(ds2),
             "--evidence-dir", str(ev), "--taxonomy-dir", str(tax),
             "--run", PROBE_RUN]), 0))
        results.append(("init_nonempty", run(
            ["init", "--dataset", str(ds),
             "--evidence-dir", str(ev), "--taxonomy-dir", str(tax),
             "--run", PROBE_RUN]), 2))
        results.append(("init_no_source", run(["init"]), 2))

        def dh(root: Path):
            from opencnmv.provenance.hashes import sha256_bytes
            return {str(p.relative_to(root)): sha256_bytes(p.read_bytes())
                    for p in sorted(root.rglob("*")) if p.is_file()}
        det = ds.is_dir() and ds2.is_dir() and dh(ds) == dh(ds2)

    ok = det and all(r["exit"] == want for _, r, want in results)
    C.jwrite(C.OUT / "wheel_smoke_g.json", {
        "wheel": wheel.name, "ok": ok,
        "two_inits_identical": det,
        "summary": f"{len(results)} commands, "
                   f"two evidence-dir inits identical: {det}",
        "results": [{"name": n, **r, "want": w}
                    for n, r, w in results]})
    print(f"wheel smoke G: {'OK' if ok else 'FAIL'} "
          f"({len(results)} commands) -> _out/wheel_smoke_g.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
