"""G2-E build step.

1. Pin-verifies the G2-C runA dataset against g2e_inputs.json
   (or regenerates the pin file with --write-inputs).
2. Builds the mini dataset (the same inline fixture the unit tests
   exercise) twice and asserts byte-identical output — the fixture is
   what the wheel smoke runs against in CI, where the pinned corpus is
   not checked out.

Usage:
    python g2e_build.py                 verify pins + build minids A/B
    python g2e_build.py --write-inputs  regenerate g2e_inputs.json
    python g2e_build.py --minids        build minids only (CI wheel smoke)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(HERE))

import g2e_common as C  # noqa: E402

INPUTS = HERE / "g2e_inputs.json"


def pin_table() -> dict:
    """sha256/rows/logical hash of every file in the pinned dataset."""
    man = C.jload(C.G2C_DS / "dataset_manifest.json")
    files = {}
    for p in sorted(C.G2C_DS.rglob("*")):
        if p.is_file():
            rel = p.relative_to(REPO).as_posix()
            files[f"g2c_runA/{p.relative_to(C.G2C_DS).as_posix()}"] = {
                "path": rel,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    for t, m in man["tables"].items():
        key = f"g2c_runA/{m['file']}"
        files[key]["rows"] = m["rows"]
        files[key]["logical_sha256"] = m["logical_sha256"]
    return {
        "gate": "G2-E-public-readonly-cli",
        "description": "Pinned input: the G2-C runA COLUMNAR_DATASET_V1 "
                       "directory, used read-only in place. g2e_run "
                       "never writes to it; corruption scenarios run on "
                       "temp copies.",
        "g2c_dataset_dir":
            "g2/G2-C-columnar-dataset-v1/_out/runA/dataset/v1",
        "g2c_corpus_logical_sha256": man["corpus_logical_sha256"],
        "g2c_dataset_version": man["dataset_version"],
        "g2c_canonical_model": man["canonical_model"],
        "files": files}


def verify_pins() -> list[str]:
    want = C.jload(INPUTS)
    got = pin_table()
    errs = []
    for k, meta in want["files"].items():
        g = got["files"].get(k)
        if g is None:
            errs.append(f"{k}: missing")
        elif g["sha256"] != meta["sha256"]:
            errs.append(f"{k}: sha256 changed")
    extra = set(got["files"]) - set(want["files"])
    if extra:
        errs.append(f"unexpected files in dataset: {sorted(extra)}")
    if got["g2c_corpus_logical_sha256"] != \
            want["g2c_corpus_logical_sha256"]:
        errs.append("corpus logical hash changed")
    return errs


def build_minids(tag: str) -> Path:
    """Materialize the tests/test_cli.py inline fixture deterministically.
    Reusing the tested fixture keeps the wheel smoke honest: CI exercises
    the exact dataset the unit suite asserts semantics over."""
    import test_cli
    dest = C.OUT / f"minids_{tag}" / "dataset" / "v1"
    if dest.exists():
        import shutil
        shutil.rmtree(dest.parent.parent)
    return test_cli.build_minids(dest)


def hash_tree(d: Path) -> dict[str, str]:
    return {p.relative_to(d).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}


def main() -> int:
    args = sys.argv[1:]
    if "--write-inputs" in args:
        C.jdump(pin_table(), INPUTS)
        print(f"wrote {INPUTS}")
        return 0
    if "--minids" not in args:
        errs = verify_pins()
        if errs:
            print("PIN FAIL:")
            for e in errs:
                print(f"  {e}")
            return 1
        print("pins OK: G2-C runA dataset matches g2e_inputs.json")
    a = build_minids("a")
    b = build_minids("b")
    # keys are relative to each minids root: equal trees == byte-identical
    ha, hb = hash_tree(a.parent.parent), hash_tree(b.parent.parent)
    if ha != hb:
        print("MINIDS NONDETERMINISTIC:")
        for k in sorted(set(ha) | set(hb)):
            if ha.get(k) != hb.get(k):
                print(f"  {k}")
        return 1
    print(f"minids deterministic: {len(ha)} files identical")
    # canonical location used by g2e_wheel / CI smoke
    canon = C.MINIDS.parent.parent
    if canon.exists():
        import shutil
        shutil.rmtree(canon)
    import shutil
    shutil.copytree(a.parent.parent, canon)
    print(f"minids at {C.MINIDS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
