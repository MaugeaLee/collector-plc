"""TCP/RTU가 공통으로 쓰는 Modbus 읽기/쓰기."""

from __future__ import annotations

from client.errors import ClientError, to_client_error
from model.error_model import ClientErrorCode


class BaseClient:
    def __init__(self, device_id: int):
        self.device_id = device_id
        self.client = self._build_client()

    def _build_client(self):
        raise NotImplementedError

    def _target(self) -> str:
        raise NotImplementedError

    def connect(self):
        try:
            ok = self.client.connect()
        except Exception as e:
            raise to_client_error(
                e, default=ClientErrorCode.CONNECT_FAILED
            ) from e
        if not ok:
            raise ClientError(
                ClientErrorCode.CONNECT_FAILED,
                f"연결 실패: {self._target()}",
            )
        return ok

    def close(self):
        self.client.close()

    def read_coils(self, address: int, count: int = 1):
        return self._read(
            lambda: self.client.read_coils(
                address, count=count, device_id=self.device_id
            )
        ).bits[:count]

    def read_discrete_inputs(self, address: int, count: int = 1):
        return self._read(
            lambda: self.client.read_discrete_inputs(
                address, count=count, device_id=self.device_id
            )
        ).bits[:count]

    def read_holding_registers(self, address: int, count: int = 1):
        return self._read(
            lambda: self.client.read_holding_registers(
                address, count=count, device_id=self.device_id
            )
        ).registers

    def read_input_registers(self, address: int, count: int = 1):
        return self._read(
            lambda: self.client.read_input_registers(
                address, count=count, device_id=self.device_id
            )
        ).registers

    def write_coil(self, address: int, value: bool):
        self._write(
            lambda: self.client.write_coil(
                address, value, device_id=self.device_id
            )
        )

    def write_register(self, address: int, value: int):
        self._write(
            lambda: self.client.write_register(
                address, value, device_id=self.device_id
            )
        )

    def write_registers(self, address: int, values: list[int]):
        self._write(
            lambda: self.client.write_registers(
                address, values, device_id=self.device_id
            )
        )

    def _read(self, call):
        try:
            return _unwrap(call(), ClientErrorCode.READ_FAILED)
        except ClientError:
            raise
        except Exception as e:
            raise to_client_error(e, default=ClientErrorCode.READ_FAILED) from e

    def _write(self, call):
        try:
            _unwrap(call(), ClientErrorCode.WRITE_FAILED)
        except ClientError:
            raise
        except Exception as e:
            raise to_client_error(e, default=ClientErrorCode.WRITE_FAILED) from e


def _unwrap(result, code: ClientErrorCode):
    if result.isError():
        raise ClientError(code, str(result))
    return result
