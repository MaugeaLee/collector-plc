"""
PLC 주기 스캔 데몬.

devices[] 각각에 대해 워커 스레드를 띄워
연결 → 주소 읽기 → MsgDataDTO 조립 → emit_data()(ZeroMQ PUB) 순으로 돈다.
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
from zeromq_client.zmq_client import ZeroMqClient

logger = logging.getLogger(__name__)

_running = True
_zmq: ZeroMqClient | None = None


def _on_signal(signum, frame):
    """종료 시그널을 받아 메인 루프 플래그를 내린다."""
    global _running
    _running = False


def build_client(device: DeviceSettings) -> BaseClient:
    """mode에 맞는 PLC 클라이언트를 생성한다."""
    if device.mode == "tcp":
        return TcpClient(device)
    if device.mode == "rtu":
        return RtuClient(device)
    if device.mode == "mc":
        return McClient(device)
    raise ValueError(f"알 수 없는 mode: {device.mode} (tcp, rtu 또는 mc)")


def now_ms() -> int:
    """현재 시각을 epoch 밀리초로 반환한다."""
    return int(time.time() * 1000)


def _as_client_error(exc: BaseException) -> ClientError:
    """예외를 ClientError로 정규화한다."""
    return exc if isinstance(exc, ClientError) else to_client_error(exc)


def _sleep_interruptible(seconds: float) -> None:
    """종료 시그널에 끊길 수 있게 짧게 나눠 잔다."""
    deadline = time.monotonic() + max(0.0, seconds)
    while _running:
        remain = deadline - time.monotonic()
        if remain <= 0:
            break
        time.sleep(min(0.2, remain))


def _safe_close(client: BaseClient) -> None:
    """PLC 연결을 best-effort로 닫는다."""
    try:
        client.close()
    except Exception as e:
        logger.debug("close failed: %s", e)


def read_addr(client: BaseClient, addr: str) -> int:
    """주소 문자열 한 건을 읽어 정수로 반환한다."""
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
    """주소 문자열 한 건에 값을 쓴다."""
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
    """번지 soft-fail용 에러 코드 문자열을 고른다."""
    if err.code is ClientErrorCode.UNSUPPORTED_ADDR:
        return err.code.value
    return (
        ClientErrorCode.ADDR_WRITE_FAILED.value
        if write
        else ClientErrorCode.ADDR_READ_FAILED.value
    )


def read_sample(client: BaseClient, addr: str) -> MsgSampleDTO:
    """단건 샘플을 읽고, 비연결 오류는 sample.error에 담는다."""
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
    """주소 목록을 순회하며 샘플 리스트를 만든다."""
    return [read_sample(client, addr) for addr in addresses]


def write_item(client: BaseClient, item: MsgWriteItemDTO) -> MsgWriteItemDTO:
    """단건 쓰고, 비연결 오류는 item.error에 담는다."""
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
    """쓰기 항목 목록을 순회 처리한다."""
    return [write_item(client, item) for item in items]


def build_write_ack(
    *,
    ref_msg_id: UUID,
    device_id: str,
    action: MsgCmdWEnum,
    results: list[MsgWriteItemDTO],
) -> MsgAckDTO:
    """쓰기 결과로 ACK 메시지를 조립한다."""
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
    """스캔 데이터 메시지를 발행한다."""
    _emit_protocol(
        cfg,
        msg_type=MsgTypeEnum.DATA,
        body=body.model_dump(mode="json"),
    )


def emit_health(cfg: Settings, body: MsgHealthDTO) -> None:
    """헬스 메시지를 발행한다."""
    _emit_protocol(
        cfg,
        msg_type=MsgTypeEnum.HEALTH,
        body=body.model_dump(mode="json"),
    )


def emit_ack(cfg: Settings, body: MsgAckDTO) -> None:
    """ACK 메시지를 발행한다."""
    _emit_protocol(
        cfg,
        msg_type=MsgTypeEnum.ACK,
        body=body.model_dump(mode="json"),
    )


def _emit_protocol(cfg: Settings, *, msg_type: MsgTypeEnum, body: dict) -> None:
    """헤더를 씌워 로그하고 ZeroMQ PUB으로 보낸다."""
    # devices[].id → collector_address / topic 세그먼트
    collector_address = body.get("device_id")
    if not collector_address:
        raise ValueError(f"{msg_type.value} body에 device_id(collector_address) 없음")
    header = ProtocolHeaderDTO(
        msg_id=uuid4(),
        gateway_address=cfg.app.gateway_address,
        collector_address=str(collector_address),
        msg_type=msg_type,
        msg_body=body,
        timestamp_ms=now_ms(),
    )
    logger.info("[%s] %s", msg_type.value.upper(), header.model_dump_json())
    zmq = _zmq
    if zmq is None:
        return
    try:
        zmq.send(header)
    except Exception as e:
        err = _as_client_error(e)
        logger.warning(
            "zmq pub failed: %s(%s) %s",
            err.code.value,
            err.code.label,
            err.detail or err,
        )


def _emit_device_health(
    cfg: Settings,
    device_id: str,
    *,
    device_ok: bool,
    reason: str | None = None,
) -> None:
    """디바이스 연결 상태를 health로 발행한다."""
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
    """스캔 주소들을 한 번 읽어 MsgDataDTO를 만든다."""
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
    """연결될 때까지 재시도하고, 종료 신호면 False를 반환한다."""
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
    """단일 디바이스의 연결·스캔·재연결 루프를 돌린다."""
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
    """ZeroMQ를 열고 디바이스 워커를 띄운 뒤 종료까지 대기한다."""
    global _running, _zmq
    cfg = cfg or settings
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info(
        "daemon start devices=%s reconnect_ms=%s",
        [d.id for d in cfg.devices],
        cfg.app.reconnect_period_ms,
    )

    zmq = ZeroMqClient(
        cfg.app.zmq,
        device_ids=[d.id for d in cfg.devices],
    )
    try:
        zmq.connect()
    except Exception as e:
        err = _as_client_error(e)
        logger.error(
            "ZeroMQ connect failed: %s(%s) %s",
            err.code.value,
            err.code.label,
            err.detail or err,
        )
        raise
    _zmq = zmq

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
        _zmq = None
        try:
            zmq.close()
        except Exception as e:
            logger.debug("zmq close failed: %s", e)
        logger.info("daemon stop")


if __name__ == "__main__":
    run()
