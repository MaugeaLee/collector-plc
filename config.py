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

from model.client_model import AppSettings, DevicesFile, Settings

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


def _load_app_from_env() -> AppSettings:
    return AppSettings(
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        gateway_address=_env_str("GATEWAY_ADDRESS", "gateway"),
        collector_address=_env_str("COLLECTOR_ADDRESS", "collector-plc"),
        reconnect_period_ms=_env_int("RECONNECT_PERIOD_MS", 5000),
    )


def load_settings() -> Settings:
    return Settings(app=_load_app_from_env(), devices=_load_devices_from_json())


settings = load_settings()
