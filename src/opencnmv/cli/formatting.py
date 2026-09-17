"""Deterministic output formatting: human tables + machine JSON/JSONL.

Machine output rules: stdout carries data only, keys sorted, no ANSI,
no localized formatting, canonical IDs verbatim, explicit null kept.
"""
from __future__ import annotations

import json
import sys


def emit_json(obj, *, out=None) -> None:
    out = out or sys.stdout
    out.write(json.dumps(obj, indent=1, ensure_ascii=False,
                         sort_keys=True, default=str))
    out.write("\n")


def emit_jsonl(rows: list, *, out=None) -> None:
    out = out or sys.stdout
    for r in rows:
        out.write(json.dumps(r, ensure_ascii=False, sort_keys=True,
                             default=str))
        out.write("\n")


def _cell(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    return s if s else "-"


def table(headers: list[str], rows: list[list], *,
          max_width: int = 60) -> str:
    """Fixed-width column table; cells truncated deterministically."""
    def trunc(s: str) -> str:
        return s if len(s) <= max_width else s[:max_width - 1] + "~"

    body = [[trunc(_cell(c)) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in body:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    lines = [line, "  ".join("-" * w for w in widths)]
    lines += ["  ".join(c.ljust(widths[i]) for i, c in enumerate(r))
              for r in body]
    return "\n".join(lines)


def kv(pairs: list[tuple[str, object]]) -> str:
    w = max(len(k) for k, _ in pairs)
    return "\n".join(f"{k.ljust(w)}  {_cell(v)}" for k, v in pairs)
