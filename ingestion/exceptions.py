"""Exceptions raised by the data foundation layer. None are swallowed silently."""
from __future__ import annotations


class DataFoundationError(Exception):
    """Base class for ingestion / validation errors."""


class MissingDataFilesError(DataFoundationError):
    """One or more expected raw CSV files are missing."""

    def __init__(self, directory: str, missing: list[str], dataset_url: str) -> None:
        self.directory = directory
        self.missing = missing
        super().__init__(
            f"Missing {len(missing)} raw file(s) in {directory}: {', '.join(missing)}. "
            f"Download the Olist dataset from {dataset_url} and extract the CSVs there."
        )


class SchemaMismatchError(DataFoundationError):
    """A raw CSV does not contain the columns the pipeline requires."""


class EmptyDatasetError(DataFoundationError):
    """A raw CSV (or a table after cleaning) contains no rows."""


class TransformationError(DataFoundationError):
    """A transformation produced an inconsistent result."""


class DatabaseConnectionError(DataFoundationError):
    """PostgreSQL cannot be reached or rejected the credentials."""
