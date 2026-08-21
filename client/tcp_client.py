"""Modbus TCP 클라이언트. 연결 설정은 생성자로 주입받는다."""

from pymodbus.client import ModbusTcpClient

from client.base_client import BaseClient
from model.client_model import TcpSettings


class TcpClient(BaseClient):
    def __init__(self, settings: TcpSettings):
        self.settings = settings
        super().__init__(device_id=settings.device_id)

    def _build_client(self):
        s = self.settings
        return ModbusTcpClient(
            host=s.host,
            port=s.port,
            timeout=s.timeout,
            retries=s.retries,
        )

    def _target(self) -> str:
        return f"{self.settings.host}:{self.settings.port}"
