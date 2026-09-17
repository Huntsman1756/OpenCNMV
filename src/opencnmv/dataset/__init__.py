"""COLUMNAR_DATASET_V1 — durable columnar materialization (G2-C).

Separates the canonical entity/model layer (small relational tables) from
the high-volume fact plane (``facts.parquet`` + normalized
``fact_dimension``). Parquet is the storage format; DuckDB is a query
surface over it — never the authoritative store.
"""
