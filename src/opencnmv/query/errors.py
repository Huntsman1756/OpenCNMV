"""Shared exceptions for the query layer (CLI exit-code mapping lives in
opencnmv.cli.errors)."""
from __future__ import annotations


class QueryError(Exception):
    """Base class for query-layer failures."""


class DatasetNotFoundError(QueryError):
    """Dataset path does not resolve to a readable COLUMNAR_DATASET_V1
    (missing directory, missing/unparseable manifest). -> exit 3"""


class DatasetIntegrityError(QueryError):
    """Dataset present but fails manifest/integrity verification.
    -> exit 5"""


class NotFoundError(QueryError):
    """A canonical object identifier does not exist. -> exit 4"""


class AmbiguousIdentifierError(QueryError):
    """An identifier resolves to more than one canonical object.
    -> exit 2"""


class MissingDependencyError(QueryError):
    """An optional dependency (duckdb/pyarrow) is not installed.
    -> exit 6"""


class UsageError(QueryError):
    """An argument value is invalid (not a resolution ambiguity).
    -> exit 2"""
