"""Ingestion errors. Messages are written to be shown to the user as-is."""


class IngestError(Exception):
    """A file could not be turned into a Document."""


class UnsupportedFormatError(IngestError):
    pass


class FileTooLargeError(IngestError):
    pass


class TooManyPagesError(IngestError):
    pass
