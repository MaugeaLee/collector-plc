"""
.env 값을 읽어 Settings로 노출한다.

사용 예:
    from config import settings
    print(settings.plc.host)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from model.client_model import (
    AppSettings,
    McSettings,
    PlcSettings,
    RtuSettings,
    Settings,
    TcpSettings,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key, default)
    return value.strip() if value is not None else default


def _env_int(key: str, default: int) -> int:
    return int(_env_str(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(_env_str(key, str(default)))


def _env_bool(key: str, default: bool) -> bool:
    value = _env_str(key, str(default)).lower()
    return value in ("1", "true", "yes", "y", "on")


def _load_plc_from_env() -> PlcSettings:
    mode = _env_str("PLC_MODE", "tcp").lower()
    device_id = _env_int("PLC_DEVICE_ID", 1)
    timeout = _env_float("PLC_TIMEOUT", 3)
    retries = _env_int("PLC_RETRIES", 3)

    if mode == "tcp":
        return TcpSettings(
            device_id=device_id,
            timeout=timeout,
            retries=retries,
            host=_env_str("PLC_TCP_HOST", "127.0.0.1"),
            port=_env_int("PLC_TCP_PORT", 502),
        )
    if mode == "rtu":
        return RtuSettings(
            device_id=device_id,
            timeout=timeout,
            retries=retries,
            port=_env_str("PLC_RTU_PORT", "COM3"),
            baudrate=_env_int("PLC_RTU_BAUDRATE", 9600),
            bytesize=_env_int("PLC_RTU_BYTESIZE", 8),
            parity=_env_str("PLC_RTU_PARITY", "N").upper(),
            stopbits=_env_float("PLC_RTU_STOPBITS", 1),
            handle_local_echo=_env_bool("PLC_RTU_HANDLE_LOCAL_ECHO", False),
        )
    if mode == "mc":
        return McSettings(
            device_id=device_id,
            timeout=timeout,
            retries=retries,
            host=_env_str("PLC_MC_HOST", "127.0.0.1"),
            port=_env_int("PLC_MC_PORT", 5000),
            plctype=_env_str("PLC_MC_PLCTYPE", "Q"),
            commtype=_env_str("PLC_MC_COMMTYPE", "binary").lower(),
        )
    raise ValueError(f"알 수 없는 PLC_MODE: {mode} (tcp, rtu 또는 mc)")


def _load_app_from_env() -> AppSettings:
    device_id = _env_int("PLC_DEVICE_ID", 1)
    return AppSettings(
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        gateway_address=_env_str("GATEWAY_ADDRESS", "gateway"),
        collector_address=_env_str("COLLECTOR_ADDRESS", "collector-plc"),
        scan_device_id=_env_str("SCAN_DEVICE_ID", str(device_id)),
        scan_addresses=[
            a.strip()
            for a in _env_str("SCAN_ADDRESSES", "D100").split(",")
            if a.strip()
        ],
        scan_period_ms=_env_int("SCAN_PERIOD_MS", 1000),
    )


def load_settings() -> Settings:
    return Settings(app=_load_app_from_env(), plc=_load_plc_from_env())


settings = load_settings()
