"""ZeroMQ 토픽 조립. collector.plc.{devices[].id}.{msg_type}."""

from __future__ import annotations

from model.protocol_model import MsgTypeEnum

COLLECTOR_KIND = "plc"
TOPIC_ROOT = "collector"


def topic_for(collector_address: str, msg_type: MsgTypeEnum | str) -> str:
    """PUB/라우팅용 전체 토픽."""
    mt = msg_type.value if isinstance(msg_type, MsgTypeEnum) else msg_type
    return f"{TOPIC_ROOT}.{COLLECTOR_KIND}.{collector_address}.{mt}"


def cmd_subscribe_prefix(collector_address: str) -> str:
    """SUB: cmd_r / cmd_w 공통 prefix."""
    return f"{TOPIC_ROOT}.{COLLECTOR_KIND}.{collector_address}.cmd_"


def instance_prefix(collector_address: str) -> str:
    """이 collector 인스턴스 전체 prefix (trailing dot)."""
    return f"{TOPIC_ROOT}.{COLLECTOR_KIND}.{collector_address}."
