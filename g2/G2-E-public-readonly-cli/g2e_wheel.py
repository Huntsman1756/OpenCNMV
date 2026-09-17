"""G2-E wheel step: build sdist+wheel, install the wheel into a clean
venv, and run the smoke corpus against the minids fixture — exercising
the installed console entry point, not the source tree.

    python g2e_wheel.py

Produces _out/wheel_smoke.json with per-command exit codes and stdout.
"""
from __future__ import annotations

import json
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import g2e_common as C  # noqa: E402

SMOKE = [
    ["--version"],
    ["--help"],
    ["--dataset", "{DS}", "dataset", "info"],
    ["--dataset", "{DS}", "dataset", "validate"],
    ["--dataset", "{DS}", "filings"],
    ["--dataset", "{DS}", "filings", "--jsonl"],
    ["--dataset", "{DS}", "filing", "cnmv:ifa:7"],
    ["--dataset", "{DS}", "history", "cnmv:ifa:8"],
    ["--dataset", "{DS}", "facts", "--state", "A-es", "--limit", "5"],
    ["--dataset", "{DS}", "fact", "fact:e10", "--json"],
    ["--dataset", "{DS}", "compare", "cnmv:ifa:7"],
    ["--dataset", "{DS}", "compare", "cnmv:ifa:8"],
    ["--dataset", "{DS}", "mappings", "cnmv:ifa:7"],
    ["--dataset", "{DS}", "events", "cnmv:ifa:8"],
    ["--dataset", "{DS}", "provenance", "--fact", "fact:e01"],
    ["--dataset", "{DS}", "filing", "cnmv:ifa:999"],   # exit 4
]


def _venv_python(env: Path) -> Path:
    s = env / ("Scripts" if sys.platform == "win32" else "bin")
    return s / ("python.exe" if sys.platform == "win32" else "python")


def main() -> int:
    if not C.MINIDS.is_dir():
        print("minids missing — run g2e_build.py first")
        return 1
    dist = REPO / "dist"
    subprocess.run([sys.executable, "-m", "build", "--no-isolation"],
                   cwd=REPO, check=True)
    wheel = sorted(dist.glob("opencnmv-*.whl"))[-1]

    env = C.OUT / "wheelenv"
    if env.exists():
        import shutil
        shutil.rmtree(env)
    venv.create(env, with_pip=True)
    py = _venv_python(env)

    # pinned runtime deps + the built wheel (no-deps: the wheel itself
    # is what we are testing; deps come from the lock)
    subprocess.run(
        [str(py), "-m", "pip", "install",
         "pydantic==2.13.4", "requests==2.33.0",
         "duckdb==1.5.5", "pyarrow==25.0.1"], check=True)
    subprocess.run(
        [str(py), "-m", "pip", "install", "--no-deps", str(wheel)],
        check=True)
    chk = subprocess.run([str(py), "-m", "pip", "check"],
                         capture_output=True, text=True)
    if chk.returncode != 0:
        print(chk.stdout + chk.stderr)
        return 1

    results = []
    for argv in SMOKE:
        argv = [a.replace("{DS}", str(C.MINIDS)) for a in argv]
        s = env / ("Scripts" if sys.platform == "win32" else "bin")
        exe = s / ("opencnmv.exe" if sys.platform == "win32"
                   else "opencnmv")
        r = subprocess.run([str(exe), *argv], capture_output=True,
                           text=True, encoding="utf-8")
        results.append({"argv": argv, "exit": r.returncode,
                        "stdout": r.stdout, "stderr": r.stderr})
    ok = all(r["exit"] == (4 if r["argv"][-1] == "cnmv:ifa:999" else 0)
             for r in results)
    C.jdump({"wheel": wheel.name, "env": str(env.relative_to(REPO)),
             "ok": ok, "results": results},
            C.OUT / "wheel_smoke.json")
    print(f"wheel smoke: {'OK' if ok else 'FAIL'} "
          f"({len(results)} commands) -> _out/wheel_smoke.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
