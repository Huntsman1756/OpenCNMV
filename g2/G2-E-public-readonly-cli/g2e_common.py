"""Shared helpers for the G2-E gate: pinned paths, in-process CLI
invocation, socket deny-all, dataset hashing, and the frozen command
corpus exercised by g2e_run / g2e_verify.

Gate code only — never imported by src/ or tests/.
"""
from __future__ import annotations

import contextlib
import io
import json
import socket
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "_out"
G2C_DS = (REPO / "g2" / "G2-C-columnar-dataset-v1" / "_out" / "runA"
          / "dataset" / "v1")
MINIDS = OUT / "minids" / "dataset" / "v1"
GOLDEN = HERE / "golden"

CORPUS_SHA256 = ("b2612152f46406a5ec4858592656c10b0afa8f98b042dc"
                 "93337782b202045f69")

TEF = "cnmv:ifa:20484"      # dual-variant lifecycle filing (not corpus)
BBVA24 = "cnmv:ifa:20448"   # the Equity +98M/-98M divergence
BBVA25 = "cnmv:ifa:20854"
SAN24 = "cnmv:ifa:20509"    # extension mappings incl. non-PROVEN
SAN25 = "cnmv:ifa:20875"
IBE24 = "cnmv:ifa:20515"    # single-variant UI-fallback filing
IBE25 = "cnmv:ifa:20934"
DUALS = {"BBVA-FY2024": BBVA24, "BBVA-FY2025": BBVA25,
         "SAN-FY2024": SAN24, "SAN-FY2025": SAN25}


class deny_network:
    """Patch every socket entry point to raise. Zero network tolerated."""

    def __init__(self):
        self.calls: list[str] = []

    def __enter__(self):
        def blocked(name):
            def _f(*a, **k):
                self.calls.append(name)
                raise AssertionError(f"network attempt: {name}")
            return _f

        self._patchers = [
            mock.patch.object(socket, n, blocked(n)) for n in
            ("socket", "create_connection", "getaddrinfo",
             "gethostbyname", "gethostbyname_ex")]
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()


def run_cli(argv: list[str]) -> dict:
    """In-process CLI run -> {"argv","exit","stdout","stderr"}."""
    from opencnmv.cli.main import entry
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            code = entry(argv)
        except SystemExit as e:      # argparse errors exit(2)
            code = int(e.code or 0)
    return {"argv": argv, "exit": code,
            "stdout": out.getvalue(), "stderr": err.getvalue()}


def ds_hashes(ds: Path) -> dict[str, str]:
    """sha256 of every file under the dataset dir, repo-relative keys."""
    import hashlib
    return {p.relative_to(ds).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ds.rglob("*")) if p.is_file()}


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def jdump(obj, p: Path) -> None:
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False,
                            sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- corpus
# The frozen command corpus. Every entry is (name, argv) where argv is
# appended after the global flags; {DS} is substituted with the dataset
# path. The corpus deliberately exercises every command, both output
# modes, the hard semantic cases, and the documented failure modes on a
# *separate corrupted copy* (never the pinned dataset).

def corpus(ds: str, ds_corrupt: str | None = None,
           ds_missing_table: str | None = None) -> list[tuple[str, list]]:
    c: list[tuple[str, list]] = [
        ("version", ["--version"]),
        ("help", ["--help"]),
        ("dataset.info", ["--dataset", ds, "dataset", "info"]),
        ("dataset.info.json",
         ["--dataset", ds, "dataset", "info", "--json"]),
        ("dataset.validate", ["--dataset", ds, "dataset", "validate",
                              "--json"]),
        ("filings", ["--dataset", ds, "filings"]),
        ("filings.jsonl", ["--dataset", ds, "filings", "--jsonl"]),
        ("filings.esef", ["--dataset", ds, "filings",
                          "--family", "ESEF_IFA"]),
        ("filings.issuer", ["--dataset", ds, "filings",
                            "--issuer", "iberdrola", "--json"]),
        ("filings.period", ["--dataset", ds, "filings",
                            "--period", "2024-12-31", "--json"]),
        ("filings.range", ["--dataset", ds, "filings",
                           "--from", "2025-01-01", "--to",
                           "2025-12-31", "--family", "IPP", "--json"]),
        ("filing.tef", ["--dataset", ds, "filing", TEF]),
        ("filing.tef.json", ["--dataset", ds, "filing", TEF, "--json"]),
        ("filing.ibe", ["--dataset", ds, "filing", IBE24, "--json"]),
        ("filing.byreg", ["--dataset", ds, "filing", "20448", "--json"]),
        ("history.tef", ["--dataset", ds, "history", TEF]),
        ("history.tef.json", ["--dataset", ds, "history", TEF,
                              "--json"]),
        ("history.variant", ["--dataset", ds, "history",
                             f"{TEF}#en", "--json"]),
        ("facts.ibe.h1", ["--dataset", ds, "facts", "--state",
                          "IBE-H1-2024", "--limit", "5"]),
        ("facts.jsonl", ["--dataset", ds, "facts", "--state",
                         "SAN-FY2024-es", "--limit", "5", "--jsonl"]),
        ("facts.count", ["--dataset", ds, "facts", "--count"]),
        ("facts.concept", ["--dataset", ds, "facts", "--filing",
                           BBVA24, "--concept", "Equity",
                           "--period", "2023-01-01", "--json"]),
        ("facts.h2dims", ["--dataset", ds, "facts", "--state",
                          "BBVA-H2-2024", "--dims",
                          "PeriodoBalanceEje", "--limit", "8",
                          "--jsonl"]),
        ("fact.typed", ["--dataset", ds, "fact",
                        "fact:4c973d3544fbd81acc29769309fc6a551ddab9"
                        "d478f813eebc88e25b59c9ffb8", "--json"]),
        ("fact.unit", ["--dataset", ds, "fact",
                       "fact:efd426dd453ad865c977c9bb5e4e1fc50408d1bc"
                       "6af9e1c25eb2fe1424e67e05", "--json"]),
        ("fact.dup", ["--dataset", ds, "fact",
                      "fact:2aeda63aecd17035c394c97c929e5c398bb794e46"
                      "826ba9e9edf624ebf82f345#1", "--json"]),
        ("compare.bbva24", ["--dataset", ds, "compare", BBVA24]),
        ("compare.bbva24.json", ["--dataset", ds, "compare", BBVA24,
                                 "--json"]),
        ("compare.ibe24", ["--dataset", ds, "compare", IBE24, "--json"]),
        ("compare.san24", ["--dataset", ds, "compare", SAN24, "--json"]),
        ("compare.bbva25", ["--dataset", ds, "compare", BBVA25,
                            "--json"]),
        ("compare.san25", ["--dataset", ds, "compare", SAN25, "--json"]),
        ("events.all", ["--dataset", ds, "events", "--jsonl"]),
        ("events.tef", ["--dataset", ds, "events", TEF]),
        ("mappings.san24", ["--dataset", ds, "mappings", SAN24]),
        ("mappings.san24.json", ["--dataset", ds, "mappings", SAN24,
                                 "--json"]),
        ("mappings.verdict", ["--dataset", ds, "mappings", SAN24,
                              "--verdict", "AMBIGUOUS", "--json"]),
        ("provenance.fact", ["--dataset", ds, "provenance", "--fact",
                             "fact:efd426dd453ad865c977c9bb5e4e1fc504"
                             "08d1bc6af9e1c25eb2fe1424e67e05",
                             "--json"]),
        ("provenance.artifact", ["--dataset", ds, "provenance",
                                 "--artifact",
                                 "sha256:75be80e13b1fb8f56a8cad06353"
                                 "a7145f0fad524f654864d70f1aa35a2cce"
                                 "94e", "--json"]),
        ("provenance.state", ["--dataset", ds, "provenance", "--state",
                              "BBVA-FY2024-es", "--json"]),
        # --- failure modes (documented exit codes) ---
        ("err.unknown_filing",
         ["--dataset", ds, "filing", "cnmv:ifa:00000"]),
        ("err.unknown_fact", ["--dataset", ds, "fact", "fact:nope"]),
        ("err.missing_dataset",
         ["--dataset", str(Path(ds).parent / "nonexistent"),
          "dataset", "info"]),
        ("err.usage", ["--dataset", ds, "filings", "--bogus-flag"]),
    ]
    if ds_corrupt:
        c += [
            ("err.corrupt_info",
             ["--dataset", ds_corrupt, "dataset", "info"]),
            ("err.corrupt_validate",
             ["--dataset", ds_corrupt, "dataset", "validate"]),
            ("err.corrupt_query",
             ["--dataset", ds_corrupt, "filings"]),
        ]
    if ds_missing_table:
        c += [
            ("err.deleted_table",
             ["--dataset", ds_missing_table, "dataset", "info"]),
        ]
    return c


MINIDS_CORPUS = [
    ("mini.info", ["dataset", "info"]),
    ("mini.validate", ["dataset", "validate"]),
    ("mini.filings", ["filings"]),
    ("mini.filing", ["filing", "cnmv:ifa:7"]),
    ("mini.history", ["history", "cnmv:ifa:8"]),
    ("mini.compare", ["compare", "cnmv:ifa:7"]),
    ("mini.facts", ["facts", "--state", "A-es", "--limit", "5"]),
    ("mini.provenance", ["provenance", "--fact", "fact:e01"]),
]
