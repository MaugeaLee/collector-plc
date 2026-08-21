"""
앱 설정은 .env, PLC 디바이스 목록은 JSON에서 읽어 Settings로 노출한다.

사용 예:
    from config import settings
    for device in settings.devices:
        print(device.id, device.mode)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from model.client_model import (
    AppSettings,
    DeviceSettings,
    DevicesFile,
    Settings,
    ZmqSettings,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_str(key: str, default: str) -> str:
    value = os.getenv(key, default)
    return value.strip() if value is not None else default


def _env_int(key: str, default: int) -> int:
    return int(_env_str(key, str(default)))


def _plc_config_path() -> Path:
    raw = _env_str("PLC_CONFIG_FILE", "plc_setting.json")
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _load_devices_from_json(path: Path | None = None) -> list:
    path = path or _plc_config_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"PLC 설정 파일이 없습니다: {path} "
            f"(plc_setting.example.json을 복사하거나 PLC_CONFIG_FILE을 확인하세요)"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"PLC 설정 JSON 파싱 실패: {path}: {e}") from e

    # 구버전 단일 객체 → devices 배열로 승격
    if isinstance(data, dict) and "devices" not in data and "mode" in data:
        data = {"devices": [data]}

    try:
        return DevicesFile.model_validate(data).devices
    except ValidationError as e:
        raise ValueError(f"PLC 설정 검증 실패: {path}: {e}") from e


def _env_bool(key: str, default: bool) -> bool:
    raw = _env_str(key, "true" if default else "false").lower()
    return raw in ("1", "true", "yes", "on")


def _load_app_from_env() -> AppSettings:
    return AppSettings(
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        gateway_address=_env_str("GATEWAY_ADDRESS", "gateway"),
        reconnect_period_ms=_env_int("RECONNECT_PERIOD_MS", 5000),
        zmq=ZmqSettings(
            pub_endpoint=_env_str("ZMQ_PUB_ENDPOINT", "tcp://127.0.0.1:5555"),
            sub_endpoint=_env_str("ZMQ_SUB_ENDPOINT", "tcp://127.0.0.1:5556"),
            pub_bind=_env_bool("ZMQ_PUB_BIND", True),
            sub_bind=_env_bool("ZMQ_SUB_BIND", False),
            recv_timeout_ms=_env_int("ZMQ_RECV_TIMEOUT_MS", 100),
            linger_ms=_env_int("ZMQ_LINGER_MS", 0),
        ),
    )


def load_settings() -> Settings:
    return Settings(app=_load_app_from_env(), devices=_load_devices_from_json())


def save_devices(
    devices: list[DeviceSettings], path: Path | None = None
) -> None:
    """devices[]를 plc_setting.json에 원자적으로 저장한다."""
    path = path or _plc_config_path()
    try:
        payload = DevicesFile(devices=devices).model_dump(mode="json")
    except ValidationError as e:
        raise ValueError(f"PLC 설정 검증 실패(저장): {path}: {e}") from e

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


settings = load_settings()
