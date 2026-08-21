from uuid import UUID
from pydantic import BaseModel
from typing import List, Optional, Union
from enum import StrEnum


class MsgTypeEnum(StrEnum):
    CMD_R = "cmd_r"
    CMD_W = "cmd_w"
    ACK = "ack"
    HEALTH = "health"
    DATA = "data"


class MsgCmdREnum(StrEnum):
    SET_SCAN = "SET_SCAN"
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
    gateway_address: str
    collector_address: str
    msg_type: MsgTypeEnum
    msg_body: dict
    timestamp_ms: int


class MsgCmdRDTO(BaseModel):
    device_id: str
    action: MsgCmdREnum
    d_address: Optional[List[str]] = None
    period_ms: Optional[int] = None
    deadline_ms: int


class MsgWriteItemDTO(BaseModel):
    addr: str
    value: int
    error: Optional[str] = None


class MsgCmdWDTO(BaseModel):
    device_id: str
    action: MsgCmdWEnum
    command: List[MsgWriteItemDTO]
    deadline_ms: int


class MsgAckDTO(BaseModel):
    ref_msg_id: UUID
    device_id: str
    action: Union[MsgCmdREnum, MsgCmdWEnum]
    status: MsgAckStatusEnum
    reason: Optional[str] = None
    applied_ms: Optional[int] = None
    results: Optional[List[MsgWriteItemDTO]] = None


class MsgHealthDTO(BaseModel):
    device_id: str
    ipc_ok: bool
    device_ok: bool
    reason: Optional[str] = None
    observed_ms: int


class MsgSampleDTO(BaseModel):
    addr: str
    value: Optional[int] = None
    error: Optional[str] = None


class MsgDataDTO(BaseModel):
    device_id: str
    sample_ms: int
    samples: List[MsgSampleDTO]
    ref_msg_id: Optional[UUID] = None
