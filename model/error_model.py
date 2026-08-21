"""클라이언트/스캔/커맨드에서 와이어로 내보내는 결과 코드.

코드 체계: E-<분류><일련번호>
  0xxx  정상 (success)
  1xxx  연결 (connection)  - 재연결 대상
  2xxx  입출력 (io)  - E-22xx 는 번지 단위 soft error
                       E-2203 은 디바이스/주소 범위 밖 (MC·Modbus 공통)
  3xxx  프로토콜/디바이스 응답 (protocol)
  4xxx  요청/설정 오류 (request)  - E-41xx 는 cmd 요청 자체가 잘못된 경우
  9xxx  분류 불가 (internal)
"""

from __future__ import annotations

from enum import StrEnum


class ClientErrorCategory(StrEnum):
    SUCCESS = "success"
    CONNECTION = "connection"
    IO = "io"
    PROTOCOL = "protocol"
    REQUEST = "request"
    INTERNAL = "internal"


class ClientErrorCode(StrEnum):
    OK = "S-0000"

    CONNECT_FAILED = "E-1001"
    CONNECTION_CLOSED = "E-1002"
    TIMEOUT = "E-1003"

    READ_FAILED = "E-2001"
    WRITE_FAILED = "E-2002"
    ADDR_READ_FAILED = "E-2201"
    ADDR_WRITE_FAILED = "E-2202"
    # MC 0x4031 / Modbus Illegal Data Address 등 — 지정 디바이스·주소가 범위 밖
    ADDR_OUT_OF_RANGE = "E-2203"

    PROTOCOL_ERROR = "E-3001"
    DEVICE_ERROR = "E-3002"

    UNSUPPORTED_ADDR = "E-4001"
    INVALID_CONFIG = "E-4002"

    # cmd_r / cmd_w 요청 자체의 결함
    CMD_BODY_INVALID = "E-4101"
    CMD_UNSUPPORTED_ACTION = "E-4102"
    CMD_UNKNOWN_DEVICE = "E-4103"
    CMD_DEVICE_MISMATCH = "E-4104"
    CMD_FIELD_MISSING = "E-4105"

    UNKNOWN = "E-9001"
    CONFIG_SAVE_FAILED = "E-9002"

    @property
    def category(self) -> ClientErrorCategory:
        # "E-1001" -> "1"
        return _CATEGORY_BY_PREFIX[self.value.split("-", 1)[1][0]]

    @property
    def label(self) -> str:
        return self.name

    @property
    def is_ok(self) -> bool:
        return self.category is ClientErrorCategory.SUCCESS

    @property
    def requires_reconnect(self) -> bool:
        return self.category is ClientErrorCategory.CONNECTION


_CATEGORY_BY_PREFIX = {
    "0": ClientErrorCategory.SUCCESS,
    "1": ClientErrorCategory.CONNECTION,
    "2": ClientErrorCategory.IO,
    "3": ClientErrorCategory.PROTOCOL,
    "4": ClientErrorCategory.REQUEST,
    "9": ClientErrorCategory.INTERNAL,
}
