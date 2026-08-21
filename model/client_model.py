"""PLC 클라이언트 / 앱 설정 스키마."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    """프로세스 공통 (로깅, 게이트웨이, 스캔 기본값)."""

    log_level: str = "INFO"
    gateway_address: str = "gateway"
    collector_address: str = "collector-plc"
    scan_device_id: str = "1"
    scan_addresses: list[str] = Field(default_factory=lambda: ["D100"])
    scan_period_ms: int = 1000


class TcpSettings(BaseModel):
    mode: Literal["tcp"] = "tcp"
    device_id: int = 1
    timeout: float = 3.0
    retries: int = 3
    host: str = "127.0.0.1"
    port: int = 502


class RtuSettings(BaseModel):
    mode: Literal["rtu"] = "rtu"
    device_id: int = 1
    timeout: float = 3.0
    retries: int = 3
    port: str = "COM3"
    baudrate: int = 9600
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1.0
    handle_local_echo: bool = False


class McSettings(BaseModel):
    mode: Literal["mc"] = "mc"
    device_id: int = 1
    timeout: float = 3.0
    retries: int = 3
    host: str = "127.0.0.1"
    port: int = 5000
    plctype: str = "Q"
    commtype: str = "binary"


PlcSettings = Annotated[
    Union[TcpSettings, RtuSettings, McSettings],
    Field(discriminator="mode"),
]


class Settings(BaseModel):
    app: AppSettings
    plc: PlcSettings
