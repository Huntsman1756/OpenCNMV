"""Incremental update engine for COLUMNAR_DATASET_V1.

Given a materialized dataset state S0 and a canonical observation O1,
derive a deterministic delta and apply it to produce S1 — preserving all
historical canonical rows and Canonical Model V1 invariants.

Submodules:
  transitions  transition vocabulary (closed set, preregistered)
  observe      observation document contract + hashing
  classify     (S0 rows, observation) -> semantic transitions
  delta        deterministic delta document (transitions + row ops)
  apply        stale-base-checked staging + publish to a dataset dir
  integrity    update-specific invariants (supersedes chains, ...)
"""
