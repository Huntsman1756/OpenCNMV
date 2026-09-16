"""Fact canonicalization — structural key vs payload (I5/I6).

fact_key:    concept | entity | period | dimensions | unit | language
payload:     value, decimals, isNil, value_sha256

No dedup by concept+period: entity/period/dimensions/unit/language are all
part of identity (R17 falsified the naive key empirically).
"""
from __future__ import annotations

import hashlib


def fact_key(concept: str, entity: str, period: str,
             dimensions: dict | None = None, unit: str | None = None,
             language: str | None = None) -> dict:
    return {"concept": concept, "entity": entity, "period": period,
            "dimensions": dimensions or {}, "unit": unit,
            "language": language}


def fact_payload(value: str | None, xvalue: str | None = None,
                 decimals: str | None = None, is_nil: bool = False) -> dict:
    return {"value": value, "xvalue": xvalue, "decimals": decimals,
            "is_nil": is_nil,
            "value_sha256": hashlib.sha256((value or "").encode("utf-8"))
            .hexdigest()}


def fact_id(key: dict, variant_version_id: str) -> str:
    canonical = "|".join([
        key["concept"], key["entity"], key["period"],
        ";".join(f"{k}={v}" for k, v in sorted(key["dimensions"].items())),
        key["unit"] or "", key["language"] or ""])
    return "fact:" + hashlib.sha256(
        f"{variant_version_id}|{canonical}".encode("utf-8")).hexdigest()
