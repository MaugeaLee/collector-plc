"""Modbus RTU 클라이언트. 설정은 config.py에서 가져온다."""

from pymodbus.client import ModbusSerialClient

import config
from client.base_client import BaseClient


class RtuClient(BaseClient):
    def _build_client(self):
        return ModbusSerialClient(
            port=config.PLC_RTU_PORT,
            baudrate=config.PLC_RTU_BAUDRATE,
            bytesize=config.PLC_RTU_BYTESIZE,
            parity=config.PLC_RTU_PARITY,
            stopbits=config.PLC_RTU_STOPBITS,
            handle_local_echo=config.PLC_RTU_HANDLE_LOCAL_ECHO,
            timeout=config.PLC_TIMEOUT,
            retries=config.PLC_RETRIES,
        )

    def _target(self) -> str:
        return config.PLC_RTU_PORT
