"""Modbus RTU 클라이언트. 연결 설정은 생성자로 주입받는다."""

from pymodbus.client import ModbusSerialClient

from client.base_client import BaseClient
from model.client_model import RtuSettings


class RtuClient(BaseClient):
    def __init__(self, settings: RtuSettings):
        self.settings = settings
        super().__init__(device_id=settings.device_id)

    def _build_client(self):
        s = self.settings
        return ModbusSerialClient(
            port=s.port,
            baudrate=s.baudrate,
            bytesize=s.bytesize,
            parity=s.parity,
            stopbits=s.stopbits,
            handle_local_echo=s.handle_local_echo,
            timeout=s.timeout,
            retries=s.retries,
        )

    def _target(self) -> str:
        return self.settings.port
