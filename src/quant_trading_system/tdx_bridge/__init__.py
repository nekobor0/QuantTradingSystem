"""TdxQuant historical daily-bar ingestion adapter."""

from .bridge import TdxIngestionBridge, payload_checksum
from .client import TdxHttpClient
from .bulk import BulkBackfillRunner, InstrumentBootstrapper, SymbolSpec
from .errors import (
    TdxBridgeError,
    TdxConfigurationError,
    TdxProtocolError,
    TdxTransportError,
)

__all__ = [
    "TdxBridgeError",
    "BulkBackfillRunner",
    "InstrumentBootstrapper",
    "SymbolSpec",
    "TdxConfigurationError",
    "TdxHttpClient",
    "TdxIngestionBridge",
    "TdxProtocolError",
    "TdxTransportError",
    "payload_checksum",
]
