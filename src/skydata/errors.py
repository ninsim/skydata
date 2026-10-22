"""Error classes. Each maps to one exit code, so a caller can tell what to retry."""


class SkydataError(Exception):
    exit_code = 1


class RequestError(SkydataError):
    """The request is invalid or asks for something undefined. Retrying will not help."""

    exit_code = 2


class DataError(SkydataError):
    """Ephemeris files or the release record are missing, stale or out of range.

    Retrying will not help until the installation is fixed.
    """

    exit_code = 3
