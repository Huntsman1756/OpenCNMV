"""OpenCNMV durable core.

Canonical layer over filings exposed through official CNMV surfaces.
Model contract: CANONICAL_MODEL_V1 (frozen at tag g1-model-frozen,
schema g1/G1-E-canonical-model-freeze/canonical_model_v1.schema.json).
Any incompatible change requires CANONICAL_MODEL_V2.
"""

__version__ = "0.1.0"
MODEL_CONTRACT = "CANONICAL_MODEL_V1"
