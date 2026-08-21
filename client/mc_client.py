"""MELSEC MC Protocol(3E) 클라이언트. 연결 설정은 생성자로 주입받는다.

BaseClient의 읽기/쓰기 API는 그대로 쓰되, 내부에서 아래 디바이스로 매핑한다.
  holding/input register -> D
  coil                  -> M
  discrete input        -> X

실제 현장 주소(D100, Y10 등)는 read_words / write_words / read_bits / write_bits 를 쓰면 된다.
"""

from __future__ import annotations

from pymcprotocol import Type3E

from client.base_client import BaseClient
from client.errors import ClientError, to_client_error
from model.client_model import McSettings
from model.error_model import ClientErrorCode


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
