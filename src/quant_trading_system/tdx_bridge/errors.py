"""Errors raised by the TdxQuant historical-data bridge."""


class TdxBridgeError(Exception):
    """Base error for transport, protocol, and bridge configuration failures."""


class TdxTransportError(TdxBridgeError):
    """The local TdxQuant HTTP endpoint could not be reached."""


class TdxProtocolError(TdxBridgeError):
    """TdxQuant returned an error or an unsupported payload."""


class TdxConfigurationError(TdxBridgeError):
    """The bridge cannot safely connect to the existing data layer."""
