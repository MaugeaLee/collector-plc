"""PLC 클라이언트 예외. 와이어에는 code만, 로그에는 detail을 쓴다."""

from __future__ import annotations

from pymodbus.exceptions import ConnectionException, ModbusException

from model.error_model import ClientErrorCode

try:
    from pymcprotocol.mcprotocolerror import MCProtocolError
except ImportError:  # pragma: no cover
    MCProtocolError = ()  # type: ignore[misc, assignment]

# MELSEC end code 0x4031 / Modbus exception 02
_MODBUS_ILLEGAL_DATA_ADDRESS = 2


class ClientError(Exception):
    def __init__(self, code: ClientErrorCode, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(detail or f"{code.value}({code.label})")


def to_client_error(
    exc: BaseException,
    *,
    default: ClientErrorCode = ClientErrorCode.UNKNOWN,
) -> ClientError:
    """라이브러리/표준 예외를 ClientError로 정규화한다."""
    if isinstance(exc, ClientError):
        return exc

    detail = str(exc)

    if isinstance(exc, TimeoutError) or "timeout" in detail.lower():
        return ClientError(ClientErrorCode.TIMEOUT, detail)

    if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
        return ClientError(ClientErrorCode.CONNECTION_CLOSED, detail)

    if isinstance(exc, (ConnectionError, ConnectionException, OSError)):
        return ClientError(ClientErrorCode.CONNECT_FAILED, detail)

    if _is_addr_out_of_range(exc, detail):
        return ClientError(ClientErrorCode.ADDR_OUT_OF_RANGE, detail)

    if isinstance(exc, ModbusException) and default is ClientErrorCode.UNKNOWN:
        return ClientError(ClientErrorCode.PROTOCOL_ERROR, detail)

    return ClientError(default, detail)


def _is_addr_out_of_range(exc: BaseException, detail: str) -> bool:
    """벤더 공통: 지정 디바이스/주소가 PLC 할당 범위 밖인지."""
    if MCProtocolError and isinstance(exc, MCProtocolError):
        if str(getattr(exc, "errorcode", "")).upper() == "0X4031":
            return True

    if getattr(exc, "exception_code", None) == _MODBUS_ILLEGAL_DATA_ADDRESS:
        return True

    upper = detail.upper()
    if "0X4031" in upper:
        return True
    if "ILLEGAL DATA ADDRESS" in upper or "EXCEPTION_CODE=2" in upper:
        return True
    return False
