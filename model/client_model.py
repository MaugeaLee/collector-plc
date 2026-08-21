"""PLC 클라이언트 / 앱 설정 스키마."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class ZmqSettings(BaseModel):
    """게이트웨이 IPC용 ZeroMQ 엔드포인트."""

    pub_endpoint: str = "tcp://127.0.0.1:5555"
    sub_endpoint: str = "tcp://127.0.0.1:5556"
    # True면 bind, False면 connect
    pub_bind: bool = True
    sub_bind: bool = False
    recv_timeout_ms: int = 100
    linger_ms: int = 0


class AppSettings(BaseModel):
    """프로세스 공통 (로깅, 게이트웨이, ZeroMQ, 재연결)."""

    log_level: str = "INFO"
    gateway_address: str = "gateway"
    reconnect_period_ms: int = 5000
    zmq: ZmqSettings = Field(default_factory=ZmqSettings)


def _validate_device_logical_id(v: str) -> str:
    # 토픽 collector.plc.{id}.{msg_type} 계층용
    if not v or "." in v:
        raise ValueError(
            "devices[].id에 '.'를 넣을 수 없습니다 "
            f"(예: plc-mitsubishi-1): {v!r}"
        )
    return v


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

    @field_validator("id")
    @classmethod
    def _id_no_dot(cls, v: str) -> str:
        return _validate_device_logical_id(v)


class RtuDevice(RtuSettings):
    id: str
    scan_addresses: list[str] = Field(default_factory=lambda: ["D100"])
    scan_period_ms: int = 1000

    @field_validator("id")
    @classmethod
    def _id_no_dot(cls, v: str) -> str:
        return _validate_device_logical_id(v)


class McDevice(McSettings):
    id: str
    scan_addresses: list[str] = Field(default_factory=lambda: ["D100"])
    scan_period_ms: int = 1000

    @field_validator("id")
    @classmethod
    def _id_no_dot(cls, v: str) -> str:
        return _validate_device_logical_id(v)


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
