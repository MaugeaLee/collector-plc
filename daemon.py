"""
PLC 주기 스캔 데몬.

연결 → 주소 읽기 → MsgDataDTO 조립 → emit_data() 순으로만 돈다.
ZeroMQ는 아직 붙이지 않고, emit_* 안에서 ProtocolHeaderDTO로 감싸 PUB 하면 된다.
"""

from __future__ import annotations

import logging
import signal
import time
from uuid import uuid4

from client.base_client import BaseClient
from client.mc_client import McClient
from client.rtu_client import RtuClient
from client.tcp_client import TcpClient
from config import settings
from model.client_model import PlcSettings, Settings
from model.protocol_model import (
    MsgDataDTO,
    MsgHealthDTO,
    MsgSampleDTO,
    MsgTypeEnum,
    ProtocolHeaderDTO,
)

logger = logging.getLogger(__name__)

_running = True


def _on_signal(signum, frame):
    global _running
    _running = False


def build_client(plc: PlcSettings) -> BaseClient:
    if plc.mode == "tcp":
        return TcpClient(plc)
    if plc.mode == "rtu":
        return RtuClient(plc)
    if plc.mode == "mc":
        return McClient(plc)
    raise ValueError(f"알 수 없는 PLC_MODE: {plc.mode} (tcp, rtu 또는 mc)")


def now_ms() -> int:
    return int(time.time() * 1000)


def read_addr(client: BaseClient, addr: str) -> int:
    """단건 읽기. D는 전 클라이언트 공통, M/X/Y는 McClient에서만."""
    kind = addr[0].upper()
    num = int(addr[1:])

    if kind == "D":
        return int(client.read_holding_registers(num, count=1)[0])

    if hasattr(client, "read_bits") and kind in ("M", "X", "Y"):
        return int(client.read_bits(addr, 1)[0])

    raise ValueError(f"지원하지 않는 주소: {addr}")


def read_samples(client: BaseClient, addresses: list[str]) -> list[MsgSampleDTO]:
    return [
        MsgSampleDTO(addr=addr, value=read_addr(client, addr))
        for addr in addresses
    ]


def emit_data(cfg: Settings, body: MsgDataDTO) -> None:
    """나중에 ZeroMQ PUB으로 교체. 지금은 로그만."""
    header = ProtocolHeaderDTO(
        msg_id=uuid4(),
        gateway_address=cfg.app.gateway_address,
        collector_address=cfg.app.collector_address,
        msg_type=MsgTypeEnum.DATA,
        msg_body=body.model_dump(mode="json"),
        timestamp_ms=now_ms(),
    )
    # TODO: zmq_sock.send_json(header.model_dump(mode="json"))
    logger.info(header.model_dump_json())


def emit_health(cfg: Settings, body: MsgHealthDTO) -> None:
    """나중에 ZeroMQ PUB으로 교체. 지금은 로그만."""
    header = ProtocolHeaderDTO(
        msg_id=uuid4(),
        gateway_address=cfg.app.gateway_address,
        collector_address=cfg.app.collector_address,
        msg_type=MsgTypeEnum.HEALTH,
        msg_body=body.model_dump(mode="json"),
        timestamp_ms=now_ms(),
    )
    # TODO: zmq_sock.send_json(header.model_dump(mode="json"))
    logger.info(header.model_dump_json())


def scan_once(cfg: Settings, client: BaseClient, addresses: list[str]) -> MsgDataDTO:
    samples = read_samples(client, addresses)
    return MsgDataDTO(
        device_id=cfg.app.scan_device_id,
        sample_ms=now_ms(),
        samples=samples,
        ref_msg_id=None,
    )


def main(cfg: Settings | None = None) -> None:
    cfg = cfg or settings
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    addresses = cfg.app.scan_addresses
    period_s = cfg.app.scan_period_ms / 1000.0
    client = build_client(cfg.plc)

    logger.info(
        "daemon start mode=%s target=%s addrs=%s period_ms=%s",
        cfg.plc.mode,
        client._target(),
        addresses,
        cfg.app.scan_period_ms,
    )

    try:
        client.connect()
        emit_health(
            cfg,
            MsgHealthDTO(
                device_id=cfg.app.scan_device_id,
                ipc_ok=True,
                device_ok=True,
                reason=None,
                observed_ms=now_ms(),
            ),
        )

        while _running:
            started = time.monotonic()
            try:
                data = scan_once(cfg, client, addresses)
                emit_data(cfg, data)
            except Exception as e:
                logger.warning("scan failed: %s", e)
                emit_health(
                    cfg,
                    MsgHealthDTO(
                        device_id=cfg.app.scan_device_id,
                        ipc_ok=True,
                        device_ok=False,
                        reason=str(e),
                        observed_ms=now_ms(),
                    ),
                )

            elapsed = time.monotonic() - started
            remain = period_s - elapsed
            if remain > 0 and _running:
                time.sleep(remain)

    finally:
        client.close()
        logger.info("daemon stop")


if __name__ == "__main__":
    main()
