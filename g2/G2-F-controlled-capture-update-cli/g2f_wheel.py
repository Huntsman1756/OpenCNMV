"""G2-F wheel step: build the wheel, install into a clean venv, and
exercise the NEW observe/update verbs through the installed console
entry point — all offline (scope rejection, missing dataset, tampered
observation, offline update --observation round-trip).

    python g2f_wheel.py

Produces _out/wheel_smoke_f.json with per-command exit codes.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(HERE))

import g2f_common as C  # noqa: E402

SMOKE = [
    (["--version"], 0),
    (["observe", "--evidence-dir", "{EV}", "--issuer", "X99999999"], 7),
    (["update", "--dataset", "{MISS}", "--observation", "{OBS}"], 3),
    (["update", "--dataset", "{DS}", "--observation", "{OBS}",
      "--dry-run"], 0),
    (["update", "--dataset", "{DS}", "--observation", "{OBS}"], 0),
    (["update", "--dataset", "{DS}", "--observation", "{TAMP}"], 5),
]


def _venv_python(env: Path) -> Path:
    s = env / ("Scripts" if sys.platform == "win32" else "bin")
    return s / ("python.exe" if sys.platform == "win32" else "python")


def main() -> int:
    # fixture: mini dataset + matching observation, built from src
    from test_capture import (build_ds, synthetic_manifest)
    from opencnmv.capture import assemble as casm
    from opencnmv.update import apply as uapply

    fix = C.OUT / "wheel_fixture"
    ds = fix / "ds"
    if not (ds / "dataset_manifest.json").is_file():
        if fix.exists():
            shutil.rmtree(fix)
        build_ds(ds)
        obs = casm.assemble_observation(
            synthetic_manifest(),
            tables=uapply.load_tables(ds), evidence_root=fix)
        C.jwrite(fix / "obs.json", obs)
        tampered = json.loads(
            (fix / "obs.json").read_text(encoding="utf-8"))
        tampered["observation_sha256"] = "0" * 64
        C.jwrite(fix / "obs_tampered.json", tampered)

    dist = REPO / "dist"
    subprocess.run([sys.executable, "-m", "build", "--no-isolation"],
                   cwd=REPO, check=True)
    wheel = sorted(dist.glob("opencnmv-*.whl"))[-1]

    env = C.OUT / "wheelenv_f"
    if env.exists():
        shutil.rmtree(env)
    venv.create(env, with_pip=True)
    py = _venv_python(env)
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

    exe = env / ("Scripts" if sys.platform == "win32" else "bin")
    exe = exe / ("opencnmv.exe" if sys.platform == "win32" else "opencnmv")
    ev = C.OUT / "wheel_ev"
    results = []
    with tempfile.TemporaryDirectory() as miss:
        for argv, want in SMOKE:
            argv = [a.replace("{DS}", str(ds))
                    .replace("{OBS}", str(fix / "obs.json"))
                    .replace("{TAMP}", str(fix / "obs_tampered.json"))
                    .replace("{EV}", str(ev))
                    .replace("{MISS}", miss + "\\nope") for a in argv]
            r = subprocess.run([str(exe), *argv], capture_output=True,
                               text=True, encoding="utf-8")
            results.append({"argv": argv, "exit": r.returncode,
                            "want": want, "stdout": r.stdout,
                            "stderr": r.stderr})
    ok = all(r["exit"] == r["want"] for r in results)
    C.jwrite(C.OUT / "wheel_smoke_f.json",
             {"wheel": wheel.name, "ok": ok, "results": results})
    print(f"wheel smoke F: {'OK' if ok else 'FAIL'} "
          f"({len(results)} commands) -> _out/wheel_smoke_f.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
