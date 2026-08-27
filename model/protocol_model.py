"""게이트웨이↔collector 프로토콜 Enum·DTO."""

from __future__ import annotations

from enum import StrEnum
from typing import List, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from model.client_model import DeviceSettings
from model.error_model import ClientErrorCode


class MsgTypeEnum(StrEnum):
    CMD_R = "cmd_r"
    CMD_W = "cmd_w"
    ACK = "ack"
    HEALTH = "health"
    DATA = "data"


class MsgCmdREnum(StrEnum):
    SET_SCAN = "SET_SCAN"
    SET_DEVICE = "SET_DEVICE"
    READ_ONCE = "READ_ONCE"
    STOP = "STOP"


class MsgCmdWEnum(StrEnum):
    CONTROL_COMMAND = "CONTROL_COMMAND"
    INSERT = "INSERT"


class MsgAckStatusEnum(StrEnum):
    OK = "ok"
    REJECTED = "rejected"
    ERROR = "error"


class ProtocolHeaderDTO(BaseModel):
    msg_id: UUID
    # 상위(게이트웨이)가 채운 값. ACK 응답 시 그대로 에코한다.
    gateway_address: str
    collector_address: str
    msg_type: MsgTypeEnum
    msg_body: dict
    timestamp_ms: int


class MsgCmdRDTO(BaseModel):
    device_key: str
    action: MsgCmdREnum
    d_address: Optional[List[str]] = None
    period_ms: Optional[int] = None
    # SET_DEVICE: DeviceSettings와 동일 (device_key는 body.device_key와 일치)
    device_setup: Optional[DeviceSettings] = None
    # 수신 시각 기준 허용 소요 시간(ms). collector가 deadline = now + timeout_ms 로 계산
    timeout_ms: int


class MsgWriteItemDTO(BaseModel):
    addr: str
    value: int
    error: Optional[str] = None


class MsgCmdWDTO(BaseModel):
    device_key: str
    action: MsgCmdWEnum
    command: List[MsgWriteItemDTO]
    # 수신 시각 기준 허용 소요 시간(ms). collector가 deadline = now + timeout_ms 로 계산
    timeout_ms: int


class MsgAckDTO(BaseModel):
    ref_msg_id: UUID
    device_key: str
    action: Union[MsgCmdREnum, MsgCmdWEnum]
    status: MsgAckStatusEnum
    # 정상은 E-0000, 그 외는 실패 사유 코드
    code: ClientErrorCode = ClientErrorCode.OK
    reason: Optional[str] = None
    applied_ms: Optional[int] = None
    results: Optional[List[MsgWriteItemDTO]] = None


class MsgHealthDTO(BaseModel):
    device_key: str
    ipc_ok: bool
    device_ok: bool
    reason: Optional[str] = None
    observed_ms: int


class MsgSampleDTO(BaseModel):
    addr: str
    value: Optional[int] = None
    error: Optional[str] = None


class MsgDataDTO(BaseModel):
    device_key: str
    sample_ms: int
    samples: List[MsgSampleDTO]
