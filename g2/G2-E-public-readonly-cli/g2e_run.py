"""G2-E run step: execute the frozen command corpus under socket
deny-all and capture every result deterministically.

    python g2e_run.py --tag A

Produces _out/run<tag>/:
    results.jsonl        one {name, argv, exit, stdout, stderr} per run
    dataset_hashes.json  sha256 of every pinned-dataset file before/after
    corrupt/             temp corrupted copies used by the corpus
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

import g2e_common as C  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="A")
    args = ap.parse_args()

    out_dir = C.OUT / f"run{args.tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="g2e_corrupt_"))

    corrupt = work / "corrupt"
    shutil.copytree(C.G2C_DS, corrupt)
    p = corrupt / "facts.parquet"
    b = bytearray(p.read_bytes())
    b[100] ^= 0xFF
    p.write_bytes(bytes(b))

    missing = work / "missing_table"
    shutil.copytree(C.G2C_DS, missing)
    (missing / "fact_dimension.parquet").unlink()

    results = []
    before = C.ds_hashes(C.G2C_DS)
    with C.deny_network() as dn:
        for name, argv in C.corpus(str(C.G2C_DS), str(corrupt),
                                   str(missing)):
            r = C.run_cli(argv)
            r["name"] = name
            results.append(r)
    after = C.ds_hashes(C.G2C_DS)

    res_path = out_dir / "results.jsonl"
    with res_path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in results:
            fh.write(__import__("json").dumps(r, ensure_ascii=False,
                                              sort_keys=True) + "\n")
    C.jdump({"before": before, "after": after,
             "identical": before == after,
             "network_attempts": dn.calls},
            out_dir / "dataset_hashes.json")
    shutil.rmtree(work, ignore_errors=True)
    print(f"run{args.tag}: {len(results)} commands, "
          f"dataset identical={before == after}, "
          f"network_attempts={len(dn.calls)} -> {res_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
