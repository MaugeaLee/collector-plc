"""TCP/RTU가 공통으로 쓰는 Modbus 읽기/쓰기."""

from pymodbus.exceptions import ModbusException


class BaseClient:
    def __init__(self, device_id: int):
        self.device_id = device_id
        self.client = self._build_client()

    def _build_client(self):
        raise NotImplementedError

    def _target(self) -> str:
        raise NotImplementedError

    def connect(self):
        ok = self.client.connect()
        if not ok:
            raise ConnectionError(f"연결 실패: {self._target()}")
        return ok

    def close(self):
        self.client.close()

    def read_coils(self, address: int, count: int = 1):
        result = self.client.read_coils(
            address, count=count, device_id=self.device_id
        )
        return _unwrap(result).bits[:count]

    def read_discrete_inputs(self, address: int, count: int = 1):
        result = self.client.read_discrete_inputs(
            address, count=count, device_id=self.device_id
        )
        return _unwrap(result).bits[:count]

    def read_holding_registers(self, address: int, count: int = 1):
        result = self.client.read_holding_registers(
            address, count=count, device_id=self.device_id
        )
        return _unwrap(result).registers

    def read_input_registers(self, address: int, count: int = 1):
        result = self.client.read_input_registers(
            address, count=count, device_id=self.device_id
        )
        return _unwrap(result).registers

    def write_coil(self, address: int, value: bool):
        result = self.client.write_coil(
            address, value, device_id=self.device_id
        )
        _unwrap(result)

    def write_register(self, address: int, value: int):
        result = self.client.write_register(
            address, value, device_id=self.device_id
        )
        _unwrap(result)

    def write_registers(self, address: int, values: list[int]):
        result = self.client.write_registers(
            address, values, device_id=self.device_id
        )
        _unwrap(result)


def _unwrap(result):
    if result.isError():
        raise ModbusException(str(result))
    return result
