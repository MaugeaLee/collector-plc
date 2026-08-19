"""
.env 값을 읽어 모듈 변수로 노출한다.

사용 예:
    import config
    print(config.PLC_TCP_HOST)
"""

from pathlib import Path

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _str(key: str, default: str) -> str:
    value = os.getenv(key, default)
    return value.strip() if value is not None else default


def _int(key: str, default: int) -> int:
    return int(_str(key, str(default)))


def _float(key: str, default: float) -> float:
    return float(_str(key, str(default)))


def _bool(key: str, default: bool) -> bool:
    value = _str(key, str(default)).lower()
    return value in ("1", "true", "yes", "y", "on")


# 통신 방식: tcp | rtu
PLC_MODE = _str("PLC_MODE", "tcp").lower()

# 공통
PLC_DEVICE_ID = _int("PLC_DEVICE_ID", 1)
PLC_TIMEOUT = _float("PLC_TIMEOUT", 3)
PLC_RETRIES = _int("PLC_RETRIES", 3)

# Modbus TCP
PLC_TCP_HOST = _str("PLC_TCP_HOST", "127.0.0.1")
PLC_TCP_PORT = _int("PLC_TCP_PORT", 502)

# Modbus RTU
PLC_RTU_PORT = _str("PLC_RTU_PORT", "COM3")
PLC_RTU_BAUDRATE = _int("PLC_RTU_BAUDRATE", 9600)
PLC_RTU_BYTESIZE = _int("PLC_RTU_BYTESIZE", 8)
PLC_RTU_PARITY = _str("PLC_RTU_PARITY", "N").upper()
PLC_RTU_STOPBITS = _float("PLC_RTU_STOPBITS", 1)
PLC_RTU_HANDLE_LOCAL_ECHO = _bool("PLC_RTU_HANDLE_LOCAL_ECHO", False)
