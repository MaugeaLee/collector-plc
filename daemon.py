"""
PLC 주기 스캔 데몬.

devices[] 각각에 대해 워커 스레드를 띄워
연결 → 주소 읽기 → MsgDataDTO 조립 → emit_data() 순으로 돈다.
연결 실패/끊김은 프로세스를 종료하지 않고 재연결한다.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from uuid import UUID, uuid4

from client.base_client import BaseClient
from client.errors import ClientError, to_client_error
from client.mc_client import McClient
from client.rtu_client import RtuClient
from client.tcp_client import TcpClient
from config import settings
from model.client_model import DeviceSettings, Settings
from model.error_model import ClientErrorCode
from model.protocol_model import (
    MsgAckDTO,
    MsgAckStatusEnum,
    MsgCmdWEnum,
    MsgDataDTO,
    MsgHealthDTO,
    MsgSampleDTO,
    MsgTypeEnum,
    MsgWriteItemDTO,
    ProtocolHeaderDTO,
)

logger = logging.getLogger(__name__)

_running = True


def _on_signal(signum, frame):
    global _running
    _running = False


def build_client(device: DeviceSettings) -> BaseClient:
    if device.mode == "tcp":
        return TcpClient(device)
    if device.mode == "rtu":
        return RtuClient(device)
    if device.mode == "mc":
        return McClient(device)
    raise ValueError(f"알 수 없는 mode: {device.mode} (tcp, rtu 또는 mc)")


def now_ms() -> int:
    return int(time.time() * 1000)


def _as_client_error(exc: BaseException) -> ClientError:
    return exc if isinstance(exc, ClientError) else to_client_error(exc)


def _sleep_interruptible(seconds: float) -> None:
    """SIGINT/SIGTERM 시 빨리 빠져나오도록 짧게 쪼개 잔다."""
    deadline = time.monotonic() + max(0.0, seconds)
    while _running:
        remain = deadline - time.monotonic()
        if remain <= 0:
            break
        time.sleep(min(0.2, remain))


def _safe_close(client: BaseClient) -> None:
    try:
        client.close()
    except Exception as e:
        logger.debug("close failed: %s", e)


def read_addr(client: BaseClient, addr: str) -> int:
    """단건 읽기. D는 전 클라이언트 공통, M/X/Y는 McClient에서만."""
    kind = addr[0].upper()
    num = int(addr[1:])

    if kind == "D":
        return int(client.read_holding_registers(num, count=1)[0])

    if hasattr(client, "read_bits") and kind in ("M", "X", "Y"):
        return int(client.read_bits(addr, 1)[0])

    raise ClientError(
        ClientErrorCode.UNSUPPORTED_ADDR,
        f"지원하지 않는 주소: {addr}",
    )


def write_addr(client: BaseClient, addr: str, value: int) -> None:
    """단건 쓰기. D는 전 클라이언트 공통, M/X/Y는 McClient에서만."""
    kind = addr[0].upper()
    num = int(addr[1:])

    if kind == "D":
        client.write_register(num, value)
        return

    if hasattr(client, "write_bits") and kind in ("M", "X", "Y"):
        client.write_bits(addr, [int(value)])
        return

    raise ClientError(
        ClientErrorCode.UNSUPPORTED_ADDR,
        f"지원하지 않는 주소: {addr}",
    )


def _addr_soft_error_code(err: ClientError, *, write: bool) -> str:
    """번지 단위 soft error. 연결성 실패는 여기 오기 전에 raise 된다."""
    if err.code is ClientErrorCode.UNSUPPORTED_ADDR:
        return err.code.value
    return (
        ClientErrorCode.ADDR_WRITE_FAILED.value
        if write
        else ClientErrorCode.ADDR_READ_FAILED.value
    )


def read_sample(client: BaseClient, addr: str) -> MsgSampleDTO:
    """단건 샘플. 연결성 실패는 전파, 그 외는 sample.error로 담는다."""
    try:
        return MsgSampleDTO(addr=addr, value=read_addr(client, addr), error=None)
    except Exception as e:
        err = _as_client_error(e)
        if err.code.requires_reconnect:
            raise err from e
        logger.warning(
            "addr read soft-fail %s: %s(%s) %s",
            addr,
            err.code.value,
            err.code.label,
            err.detail or err,
        )
        return MsgSampleDTO(
            addr=addr,
            value=None,
            error=_addr_soft_error_code(err, write=False),
        )


def read_samples(client: BaseClient, addresses: list[str]) -> list[MsgSampleDTO]:
    return [read_sample(client, addr) for addr in addresses]


def write_item(client: BaseClient, item: MsgWriteItemDTO) -> MsgWriteItemDTO:
    """단건 쓰기. 연결성 실패는 전파, 그 외는 item.error로 담는다."""
    try:
        write_addr(client, item.addr, item.value)
        return MsgWriteItemDTO(addr=item.addr, value=item.value, error=None)
    except Exception as e:
        err = _as_client_error(e)
        if err.code.requires_reconnect:
            raise err from e
        logger.warning(
            "addr write soft-fail %s: %s(%s) %s",
            item.addr,
            err.code.value,
            err.code.label,
            err.detail or err,
        )
        return MsgWriteItemDTO(
            addr=item.addr,
            value=item.value,
            error=_addr_soft_error_code(err, write=True),
        )


def write_items(
    client: BaseClient, items: list[MsgWriteItemDTO]
) -> list[MsgWriteItemDTO]:
    return [write_item(client, item) for item in items]


def build_write_ack(
    *,
    ref_msg_id: UUID,
    device_id: str,
    action: MsgCmdWEnum,
    results: list[MsgWriteItemDTO],
) -> MsgAckDTO:
    """번지별 결과로 ACK 조립. 전부 성공이면 ok, 일부/전부 soft-fail이면 error."""
    failed = [r for r in results if r.error]
    if not failed:
        status = MsgAckStatusEnum.OK
        reason = None
    else:
        status = MsgAckStatusEnum.ERROR
        reason = failed[0].error
    return MsgAckDTO(
        ref_msg_id=ref_msg_id,
        device_id=device_id,
        action=action,
        status=status,
        reason=reason,
        applied_ms=now_ms(),
        results=results,
    )


def emit_data(cfg: Settings, body: MsgDataDTO) -> None:
    """나중에 ZeroMQ PUB으로 교체. 지금은 로그만."""
    _emit_protocol(
        cfg,
        msg_type=MsgTypeEnum.DATA,
        body=body.model_dump(mode="json"),
    )


def emit_health(cfg: Settings, body: MsgHealthDTO) -> None:
    """나중에 ZeroMQ PUB으로 교체. 지금은 로그만."""
    _emit_protocol(
        cfg,
        msg_type=MsgTypeEnum.HEALTH,
        body=body.model_dump(mode="json"),
    )


def emit_ack(cfg: Settings, body: MsgAckDTO) -> None:
    """나중에 ZeroMQ PUB으로 교체. 지금은 로그만."""
    _emit_protocol(
        cfg,
        msg_type=MsgTypeEnum.ACK,
        body=body.model_dump(mode="json"),
    )


def _emit_protocol(cfg: Settings, *, msg_type: MsgTypeEnum, body: dict) -> None:
    header = ProtocolHeaderDTO(
        msg_id=uuid4(),
        gateway_address=cfg.app.gateway_address,
        collector_address=cfg.app.collector_address,
        msg_type=msg_type,
        msg_body=body,
        timestamp_ms=now_ms(),
    )
    # TODO: zmq_sock.send_json(header.model_dump(mode="json"))
    logger.info("[%s] %s", msg_type.value.upper(), header.model_dump_json())


def _emit_device_health(
    cfg: Settings,
    device_id: str,
    *,
    device_ok: bool,
    reason: str | None = None,
) -> None:
    emit_health(
        cfg,
        MsgHealthDTO(
            device_id=device_id,
            ipc_ok=True,
            device_ok=device_ok,
            reason=reason,
            observed_ms=now_ms(),
        ),
    )


def scan_once(
    device: DeviceSettings,
    client: BaseClient,
) -> MsgDataDTO:
    samples = read_samples(client, device.scan_addresses)
    return MsgDataDTO(
        device_id=device.id,
        sample_ms=now_ms(),
        samples=samples,
        ref_msg_id=None,
    )


def ensure_connected(
    cfg: Settings,
    device: DeviceSettings,
    client: BaseClient,
    reconnect_s: float,
) -> bool:
    """연결될 때까지 재시도. 성공 True, 종료 신호면 False."""
    while _running:
        try:
            client.connect()
            logger.info("[%s] connected: %s", device.id, client._target())
            _emit_device_health(cfg, device.id, device_ok=True)
            return True
        except ClientError as e:
            logger.error(
                "[%s] connect failed: %s(%s) %s",
                device.id,
                e.code.value,
                e.code.label,
                e.detail or e,
            )
            _emit_device_health(
                cfg, device.id, device_ok=False, reason=e.code.value
            )
            _safe_close(client)
            _sleep_interruptible(reconnect_s)
    return False


def run_device(cfg: Settings, device: DeviceSettings) -> None:
    """단일 디바이스 스캔 루프 (스레드에서 실행)."""
    period_s = device.scan_period_ms / 1000.0
    reconnect_s = cfg.app.reconnect_period_ms / 1000.0
    client = build_client(device)

    logger.info(
        "[%s] worker start mode=%s target=%s addrs=%s period_ms=%s",
        device.id,
        device.mode,
        client._target(),
        device.scan_addresses,
        device.scan_period_ms,
    )

    try:
        while _running:
            if not ensure_connected(cfg, device, client, reconnect_s):
                break

            while _running:
                started = time.monotonic()
                try:
                    data = scan_once(device, client)
                    emit_data(cfg, data)
                except Exception as e:
                    # 연결성 등 스캔 단위 실패만 HEALTH. 번지 soft-fail은 DATA에 포함.
                    err = _as_client_error(e)
                    logger.warning(
                        "[%s] scan failed: %s(%s) %s",
                        device.id,
                        err.code.value,
                        err.code.label,
                        err.detail or err,
                    )
                    if err.code.requires_reconnect:
                        _emit_device_health(
                            cfg,
                            device.id,
                            device_ok=False,
                            reason=err.code.value,
                        )
                        logger.warning(
                            "[%s] reconnecting due to %s",
                            device.id,
                            err.code.label,
                        )
                        _safe_close(client)
                        break
                    logger.error(
                        "[%s] unexpected scan error (no reconnect): %s",
                        device.id,
                        err.detail or err,
                    )

                elapsed = time.monotonic() - started
                remain = period_s - elapsed
                if remain > 0 and _running:
                    _sleep_interruptible(remain)
    finally:
        _safe_close(client)
        logger.info("[%s] worker stop", device.id)


def run(cfg: Settings | None = None) -> None:
    global _running
    cfg = cfg or settings
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info(
        "daemon start devices=%s reconnect_ms=%s",
        [d.id for d in cfg.devices],
        cfg.app.reconnect_period_ms,
    )

    threads = [
        threading.Thread(
            target=run_device,
            args=(cfg, device),
            name=f"plc-{device.id}",
            daemon=True,
        )
        for device in cfg.devices
    ]
    for t in threads:
        t.start()

    try:
        while _running:
            time.sleep(0.2)
    finally:
        _running = False
        for t in threads:
            t.join(timeout=cfg.app.reconnect_period_ms / 1000.0 + 2.0)
        logger.info("daemon stop")


if __name__ == "__main__":
    run()
