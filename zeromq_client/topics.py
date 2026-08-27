"""ZeroMQ 토픽 조립. collector.plc.{devices[].device_key}.{msg_type}."""

from __future__ import annotations

from model.protocol_model import MsgTypeEnum

COLLECTOR_KIND = "plc"
PUB_TOPIC_ROOT = "collector"

def topic_for(collector_address: str, msg_type: MsgTypeEnum | str) -> str:
    """PUB/라우팅용 전체 토픽."""
    mt = msg_type.value if isinstance(msg_type, MsgTypeEnum) else msg_type
    return f"{PUB_TOPIC_ROOT}.{COLLECTOR_KIND}.{collector_address}.{mt}"


def cmd_subscribe_prefix(collector_address: str) -> str:
    """SUB: cmd_r / cmd_w 공통 prefix."""
    return f"middleware.gateway.cmd_"

