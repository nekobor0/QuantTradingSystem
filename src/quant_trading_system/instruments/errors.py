"""Stable domain errors for the instruments module."""

from __future__ import annotations


class InstrumentError(Exception):
    """Base exception with an API-safe, stable error code."""

    code = "INSTRUMENT_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidInstrument(InstrumentError):
    code = "INVALID_INSTRUMENT"


class InvalidDateRange(InstrumentError):
    code = "INVALID_DATE_RANGE"


class InvalidTradingSpec(InstrumentError):
    code = "INVALID_TRADING_SPEC"


class InstrumentNotFound(InstrumentError):
    code = "INSTRUMENT_NOT_FOUND"


class AliasAmbiguous(InstrumentError):
    code = "ALIAS_AMBIGUOUS"


class TradingSpecNotFound(InstrumentError):
    code = "TRADING_SPEC_NOT_FOUND"


class ValidityOverlap(InstrumentError):
    code = "VALIDITY_OVERLAP"


class InvalidLifecycleTransition(InstrumentError):
    code = "INVALID_LIFECYCLE_TRANSITION"


class SourceRecordConflict(InstrumentError):
    code = "SOURCE_RECORD_CONFLICT"


class RepositoryConflict(InstrumentError):
    code = "REPOSITORY_CONFLICT"
