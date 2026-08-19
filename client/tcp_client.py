"""Modbus TCP 클라이언트. 설정은 config.py에서 가져온다."""

from pymodbus.client import ModbusTcpClient

import config
from client.base_client import BaseClient


class TcpClient(BaseClient):
    def _build_client(self):
        return ModbusTcpClient(
            host=config.PLC_TCP_HOST,
            port=config.PLC_TCP_PORT,
            timeout=config.PLC_TIMEOUT,
            retries=config.PLC_RETRIES,
        )

    def _target(self) -> str:
        return f"{config.PLC_TCP_HOST}:{config.PLC_TCP_PORT}"
