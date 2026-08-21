"""PLC 클라이언트 / 앱 설정 스키마."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


class AppSettings(BaseModel):
    """프로세스 공통 (로깅, 게이트웨이, 재연결)."""

    log_level: str = "INFO"
    gateway_address: str = "gateway"
    collector_address: str = "collector-plc"
    reconnect_period_ms: int = 5000


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


class TcpDevice(TcpSettings):
    """연결 + 스캔 설정을 포함한 디바이스."""

    id: str
    scan_addresses: list[str] = Field(default_factory=lambda: ["D100"])
    scan_period_ms: int = 1000


class RtuDevice(RtuSettings):
    id: str
    scan_addresses: list[str] = Field(default_factory=lambda: ["D100"])
    scan_period_ms: int = 1000


class McDevice(McSettings):
    id: str
    scan_addresses: list[str] = Field(default_factory=lambda: ["D100"])
    scan_period_ms: int = 1000


DeviceSettings = Annotated[
    Union[TcpDevice, RtuDevice, McDevice],
    Field(discriminator="mode"),
]


class DevicesFile(BaseModel):
    """plc_setting.json 루트."""

    devices: list[DeviceSettings] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> DevicesFile:
        ids = [d.id for d in self.devices]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"device id 중복: {sorted(dup)}")
        return self


class Settings(BaseModel):
    app: AppSettings
    devices: list[DeviceSettings]
