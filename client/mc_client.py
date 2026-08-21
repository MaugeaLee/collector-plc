"""MELSEC MC Protocol(3E) 클라이언트. 연결 설정은 생성자로 주입받는다.

BaseClient의 읽기/쓰기 API는 그대로 쓰되, 내부에서 아래 디바이스로 매핑한다.
  holding/input register -> D
  coil                  -> M
  discrete input        -> X

현장 주소 문자열(D100, R0, M10, Y10 등)은 read_device / write_device
또는 read_words / write_words / read_bits / write_bits 로 지정한다.
"""

from __future__ import annotations

import re

from pymcprotocol import Type3E

from client.base_client import BaseClient
from client.errors import ClientError, to_client_error
from model.client_model import McSettings
from model.error_model import ClientErrorCode

# pymcprotocol headdevice: 디바이스명 + 10진 번호 (예: D100, ZR0, M10)
_ADDR_RE = re.compile(r"^([A-Za-z]+)(\d+)$")

# 워드 단위 접근
_WORD_DEVICES = frozenset({"D", "W", "R", "ZR", "SD", "SW", "Z"})
# 비트 단위 접근
_BIT_DEVICES = frozenset({"M", "X", "Y", "B", "L", "F", "SM"})


def parse_mc_addr(addr: str) -> tuple[str, int]:
    """'D100' / 'R0' / 'ZR10' → (디바이스, 번호)."""
    m = _ADDR_RE.match(addr.strip())
    if not m:
        raise ClientError(
            ClientErrorCode.UNSUPPORTED_ADDR,
            f"지원하지 않는 주소 형식: {addr}",
        )
    return m.group(1).upper(), int(m.group(2))


class McClient(BaseClient):
    def __init__(self, settings: McSettings):
        self.settings = settings
        super().__init__(device_id=settings.device_id)

    def _build_client(self):
        s = self.settings
        plc = Type3E(plctype=s.plctype)
        plc.setaccessopt(
            commtype=s.commtype,
            timer_sec=max(1, int(s.timeout)),
        )
        plc.soc_timeout = s.timeout
        return plc

    def _target(self) -> str:
        return f"{self.settings.host}:{self.settings.port}"

    def connect(self):
        try:
            self.client.connect(self.settings.host, self.settings.port)
        except Exception as e:
            err = to_client_error(e, default=ClientErrorCode.CONNECT_FAILED)
            raise ClientError(
                err.code,
                f"연결 실패: {self._target()}: {err.detail or e}",
            ) from e
        return True

    def read_words(self, headdevice: str, count: int = 1):
        return self._mc_call(
            ClientErrorCode.READ_FAILED,
            lambda: self.client.batchread_wordunits(
                headdevice=headdevice, readsize=count
            ),
        )

    def write_words(self, headdevice: str, values: list[int]):
        self._mc_call(
            ClientErrorCode.WRITE_FAILED,
            lambda: self.client.batchwrite_wordunits(
                headdevice=headdevice, values=values
            ),
        )

    def read_bits(self, headdevice: str, count: int = 1):
        return self._mc_call(
            ClientErrorCode.READ_FAILED,
            lambda: self.client.batchread_bitunits(
                headdevice=headdevice, readsize=count
            ),
        )

    def write_bits(self, headdevice: str, values: list[int]):
        self._mc_call(
            ClientErrorCode.WRITE_FAILED,
            lambda: self.client.batchwrite_bitunits(
                headdevice=headdevice, values=values
            ),
        )

    def read_device(self, addr: str, count: int = 1) -> list[int]:
        """주소 문자열(D100, R0, M10 …)을 읽어 정수 리스트로 반환한다."""
        kind, num = parse_mc_addr(addr)
        head = f"{kind}{num}"
        if kind in _WORD_DEVICES:
            return [int(v) for v in self.read_words(head, count)]
        if kind in _BIT_DEVICES:
            return [int(v) for v in self.read_bits(head, count)]
        raise ClientError(
            ClientErrorCode.UNSUPPORTED_ADDR,
            f"지원하지 않는 주소: {addr}",
        )

    def write_device(self, addr: str, values: list[int]) -> None:
        """주소 문자열에 값을 쓴다. values 길이가 연속 워드/비트 개수."""
        kind, num = parse_mc_addr(addr)
        head = f"{kind}{num}"
        if kind in _WORD_DEVICES:
            self.write_words(head, [int(v) for v in values])
            return
        if kind in _BIT_DEVICES:
            self.write_bits(head, [int(v) for v in values])
            return
        raise ClientError(
            ClientErrorCode.UNSUPPORTED_ADDR,
            f"지원하지 않는 주소: {addr}",
        )

    def read_holding_registers(self, address: int, count: int = 1):
        return self.read_words(f"D{address}", count)

    def read_input_registers(self, address: int, count: int = 1):
        return self.read_holding_registers(address, count)

    def read_coils(self, address: int, count: int = 1):
        return [bool(v) for v in self.read_bits(f"M{address}", count)]

    def read_discrete_inputs(self, address: int, count: int = 1):
        return [bool(v) for v in self.read_bits(f"X{address}", count)]

    def write_coil(self, address: int, value: bool):
        self.write_bits(f"M{address}", [int(value)])

    def write_register(self, address: int, value: int):
        self.write_words(f"D{address}", [value])

    def write_registers(self, address: int, values: list[int]):
        self.write_words(f"D{address}", values)

    def _mc_call(self, default: ClientErrorCode, call):
        try:
            return call()
        except ClientError:
            raise
        except Exception as e:
            raise to_client_error(e, default=default) from e
