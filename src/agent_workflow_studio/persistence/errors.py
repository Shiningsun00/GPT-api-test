class PersistenceError(Exception):
    """Base error for durable domain persistence."""


class SchemaVersionError(PersistenceError):
    pass


class PersistenceConflictError(PersistenceError):
    pass


class ImmutableEntityError(PersistenceConflictError):
    pass


class SecretPersistenceError(PersistenceError):
    pass
