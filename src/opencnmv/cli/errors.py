"""CLI error surface: frozen exit-code vocabulary for CLI V1.

    0  success
    1  unexpected internal error (never a bare traceback)
    2  usage error (bad args, ambiguous identifier, invalid filter value)
    3  dataset missing / unreadable
    4  canonical object not found
    5  dataset integrity failure
    6  unsupported operation / optional dependency unavailable
"""
from __future__ import annotations

from opencnmv.query.errors import (
    AmbiguousIdentifierError, DatasetIntegrityError, DatasetNotFoundError,
    MissingDependencyError, NotFoundError, QueryError, UsageError)

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_DATASET_MISSING = 3
EXIT_NOT_FOUND = 4
EXIT_INTEGRITY = 5
EXIT_UNSUPPORTED = 6

_EXIT_CODES = (
    (DatasetNotFoundError, EXIT_DATASET_MISSING),
    (DatasetIntegrityError, EXIT_INTEGRITY),
    (AmbiguousIdentifierError, EXIT_USAGE),
    (UsageError, EXIT_USAGE),
    (NotFoundError, EXIT_NOT_FOUND),
    (MissingDependencyError, EXIT_UNSUPPORTED),
    (QueryError, EXIT_USAGE),
)


def exit_code_for(exc: BaseException) -> int:
    for cls, code in _EXIT_CODES:
        if isinstance(exc, cls):
            return code
    return EXIT_USAGE
