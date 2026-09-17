"""Controlled capture — the ONLY network-capable production path.

``opencnmv.capture`` walks the official CNMV surfaces, preserves raw
bytes write-once, and assembles ``CANONICAL_OBSERVATION_V1`` documents
that the offline update engine (``opencnmv.update``) consumes.

Scope is hard-frozen (AGENTS.md §4): issuers SAN/BBVA/IBE, ESEF
FY2024/FY2025, IPP H1-2024 .. H1-2026. Nothing here widens that.
"""
