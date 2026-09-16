"""extension_mapping records (G1-C contract, I9).

Only PROVEN_EQUIVALENT mappings may rewrite cross-variant fact identity;
AMBIGUOUS / CONFLICT / UNMATCHED elements are never merged.
"""
from __future__ import annotations

PROVEN = "PROVEN_EQUIVALENT"
NON_REWRITING = {"AMBIGUOUS", "CONFLICT", "UNMATCHED"}


def mapping_record(filing_id: str, source_lang: str, target_lang: str,
                   rec: dict) -> dict:
    return {"pair_id": rec["pair_id"], "filing_id": filing_id,
            "source_variant_id": f"{filing_id}#{source_lang}",
            "target_variant_id": f"{filing_id}#{target_lang}",
            "source_qname": rec["source_qname"],
            "target_qname": rec["target_qname"],
            "mapping_type": rec["mapping_type"],
            "verdict": rec["verdict"],
            "evidence": rec.get("evidence", [])}


def rewrites_identity(rec: dict) -> bool:
    return rec["verdict"] == PROVEN
