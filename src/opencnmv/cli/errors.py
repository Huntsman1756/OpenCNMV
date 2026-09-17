"""CLI error surface: frozen exit-code vocabulary for CLI V1.

    0  success
    1  unexpected internal error (never a bare traceback)
    2  usage error (bad args, ambiguous identifier, invalid filter value)
    3  dataset missing / unreadable
    4  canonical object not found
    5  dataset integrity failure (incl. stale base, tampered
       observation/delta, unresolved source state under
       --fail-on-unresolved)
    6  unsupported operation / optional dependency unavailable
    7  capture/source failure (CNMV unreachable, non-200, unexpected
       shape, issuer-selection ambiguity, retrieval limits exceeded)
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
EXIT_CAPTURE = 7


def exit_code_for(exc: BaseException) -> int:
    from opencnmv.capture.contract import CaptureError
    from opencnmv.update.observe import ObservationError

    if isinstance(exc, CaptureError):
        return EXIT_CAPTURE
    # update.apply pulls in dataset/pyarrow lazily; under a missing optional
    # dependency that import itself fails — those error classes cannot have
    # been raised in that case, so skipping them preserves the mapping.
    try:
        from opencnmv.update.apply import DeltaError, StaleBaseError
        update_errs: tuple[type[BaseException], ...] = (
            StaleBaseError, DeltaError, ObservationError)
    except ImportError:
        update_errs = (ObservationError,)
    if isinstance(exc, update_errs):
        return EXIT_INTEGRITY
    if isinstance(exc, FileNotFoundError):
        return EXIT_DATASET_MISSING
    for cls, code in (
            (DatasetNotFoundError, EXIT_DATASET_MISSING),
            (DatasetIntegrityError, EXIT_INTEGRITY),
            (AmbiguousIdentifierError, EXIT_USAGE),
            (UsageError, EXIT_USAGE),
            (NotFoundError, EXIT_NOT_FOUND),
            (MissingDependencyError, EXIT_UNSUPPORTED)):
        if isinstance(exc, cls):
            return code
    if isinstance(exc, QueryError):
        return EXIT_USAGE
    return EXIT_INTERNAL
