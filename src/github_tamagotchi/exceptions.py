"""Domain exception hierarchy.

Repositories catch SQLAlchemy errors and re-raise as one of these.
Services and routes never see SQLAlchemy internals.
"""


class AppError(Exception):
    """Base for all application domain errors."""


class RepositoryError(AppError):
    """A database operation failed unexpectedly."""


class NotFoundError(RepositoryError):
    """The requested record does not exist."""


class ConflictError(RepositoryError):
    """A uniqueness or integrity constraint was violated."""


class ConstraintError(RepositoryError):
    """A check or foreign-key constraint was violated."""
