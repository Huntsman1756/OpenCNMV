# Synthetic reproducer for the Arelle base64Binary lexical-validation MemoryError
# found by R12 (kept for a future upstream report after G0-R closes).
#
#   arelle-release 2.44.0 (and 2.45.0 — identical pattern):
#   arelle/XmlValidate.py  lexicalPatterns["base64Binary"] is a
#   nested-quantifier regex compiled with the third-party `regex` module.
#   Matching it against a multi-MB base64 value — e.g. the embedded-PDF
#   xbrli:base64BinaryItemType facts in CNMV IPP instances (~8 MB each) —
#   raises MemoryError during instanceDiscover -> xmlValidate.
#
# Usage:  python arelle_base64_reproducer.py --run
# Runs in a child process is recommended: the original pattern can consume
# all available RAM before raising MemoryError.

import base64, sys


def main() -> int:
    if "--run" not in sys.argv:
        print("pass --run to execute (can consume all RAM before MemoryError)")
        return 2
    from arelle.XmlValidate import lexicalPatterns
    payload = base64.b64encode(b"\xab" * (9 * 1024 * 1024)).decode("ascii")
    print(f"payload: {len(payload):,} chars; pattern: "
          f"{lexicalPatterns['base64Binary'].pattern[:60]}...")
    try:
        ok = lexicalPatterns["base64Binary"].match(payload) is not None
        print(f"matched={ok} (no MemoryError — upstream may have fixed it)")
        return 0
    except MemoryError:
        print("MemoryError — bug reproduced")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
