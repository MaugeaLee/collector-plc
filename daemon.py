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
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from client.base_client import BaseClient
from client.errors import ClientError, to_client_error
from client.mc_client import McClient
from client.rtu_client import RtuClient
from client.tcp_client import TcpClient
from config import save_devices, settings
from model.client_model import DeviceSettings, Settings
from model.error_model import ClientErrorCategory, ClientErrorCode
from model.protocol_model import (
    MsgAckDTO,
    MsgAckStatusEnum,
    MsgCmdREnum,
    MsgCmdRDTO,
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
_device_adapter = TypeAdapter(DeviceSettings)


@dataclass
class DeviceSlot:
    """디바이스 워커가 공유하는 최신 설정·리로드 신호."""

    device: DeviceSettings
    lock: threading.Lock = field(default_factory=threading.Lock)
    reload: threading.Event = field(default_factory=threading.Event)


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


def _as_error_code(value: str | None) -> ClientErrorCode:
    """와이어의 코드 문자열을 ClientErrorCode로 되돌린다."""
    try:
        return ClientErrorCode(value)
    except ValueError:
        return ClientErrorCode.UNKNOWN


def _sleep_interruptible(
    seconds: float, wake: threading.Event | None = None
) -> None:
    """종료 시그널(및 선택적 wake)에 끊길 수 있게 짧게 나눠 잔다."""
    deadline = time.monotonic() + max(0.0, seconds)
    while _running:
        if wake is not None and wake.is_set():
            break
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
    # MC: D/R/M/X… 문자열을 그대로 디바이스 지정
    if hasattr(client, "read_device"):
        return int(client.read_device(addr, 1)[0])

    kind = addr[0].upper()
    num = int(addr[1:])

    if kind == "D":
        return int(client.read_holding_registers(num, count=1)[0])

    raise ClientError(
        ClientErrorCode.UNSUPPORTED_ADDR,
        f"지원하지 않는 주소: {addr}",
    )


def write_addr(client: BaseClient, addr: str, value: int) -> None:
    """주소 문자열 한 건에 값을 쓴다."""
    if hasattr(client, "write_device"):
        client.write_device(addr, [int(value)])
        return

    kind = addr[0].upper()
    num = int(addr[1:])

    if kind == "D":
        client.write_register(num, value)
        return

    raise ClientError(
        ClientErrorCode.UNSUPPORTED_ADDR,
        f"지원하지 않는 주소: {addr}",
    )


def _addr_soft_error_code(err: ClientError, *, write: bool) -> str:
    """번지 soft-fail용 에러 코드 문자열을 고른다."""
    # 의미가 분명한 번지 오류는 그대로 노출 (E-2201/2202로 덮지 않음)
    if err.code in (
        ClientErrorCode.UNSUPPORTED_ADDR,
        ClientErrorCode.ADDR_OUT_OF_RANGE,
    ):
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
        code = ClientErrorCode.OK
        reason = None
    else:
        status = MsgAckStatusEnum.ERROR
        code = _as_error_code(failed[0].error)
        reason = failed[0].error
    return MsgAckDTO(
        ref_msg_id=ref_msg_id,
        device_id=device_id,
        action=action,
        status=status,
        code=code,
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


def _snapshot_devices(slots: dict[str, DeviceSlot]) -> list[DeviceSettings]:
    """슬롯의 최신 device 스냅샷 목록."""
    out: list[DeviceSettings] = []
    for slot in slots.values():
        with slot.lock:
            out.append(slot.device.model_copy(deep=True))
    return out


def _persist_slots(
    slots: dict[str, DeviceSlot], *, override: DeviceSettings | None = None
) -> None:
    """런타임 devices[]를 plc_setting.json에 저장한다."""
    devices = _snapshot_devices(slots)
    if override is not None:
        devices = [override if d.id == override.id else d for d in devices]
    save_devices(devices)


def _ack_status(code: ClientErrorCode) -> MsgAckStatusEnum:
    """요청 결함은 rejected, 처리 중 실패는 error로 구분한다."""
    if code.is_ok:
        return MsgAckStatusEnum.OK
    if code.category is ClientErrorCategory.REQUEST:
        return MsgAckStatusEnum.REJECTED
    return MsgAckStatusEnum.ERROR


def _emit_cmd_ack(
    cfg: Settings,
    *,
    ref_msg_id: UUID,
    device_id: str,
    action: MsgCmdREnum | MsgCmdWEnum,
    code: ClientErrorCode = ClientErrorCode.OK,
    reason: str | None = None,
) -> None:
    status = _ack_status(code)
    emit_ack(
        cfg,
        MsgAckDTO(
            ref_msg_id=ref_msg_id,
            device_id=device_id,
            action=action,
            status=status,
            code=code,
            reason=reason or (None if code.is_ok else code.label),
            applied_ms=now_ms() if status is MsgAckStatusEnum.OK else None,
            results=None,
        ),
    )


def _commit_device(
    cfg: Settings,
    slots: dict[str, DeviceSlot],
    slot: DeviceSlot,
    header: ProtocolHeaderDTO,
    body: MsgCmdRDTO,
    data: dict,
    *,
    reload_client: bool,
) -> None:
    """설정 dict를 검증 → 저장 → 슬롯 반영 순으로 커밋하고 ACK를 낸다."""
    try:
        new_device = _device_adapter.validate_python(data)
    except ValidationError as e:
        logger.warning(
            "[%s] %s invalid device setup: %s",
            body.device_id,
            body.action.value,
            e,
        )
        _emit_cmd_ack(
            cfg,
            ref_msg_id=header.msg_id,
            device_id=body.device_id,
            action=body.action,
            code=ClientErrorCode.INVALID_CONFIG,
        )
        return

    if new_device.id != body.device_id:
        _emit_cmd_ack(
            cfg,
            ref_msg_id=header.msg_id,
            device_id=body.device_id,
            action=body.action,
            code=ClientErrorCode.CMD_DEVICE_MISMATCH,
            reason=f"device_setup.id={new_device.id}",
        )
        return

    # 저장이 실패하면 런타임도 바꾸지 않는다 (파일·메모리 불일치 방지)
    try:
        _persist_slots(slots, override=new_device)
    except Exception as e:
        err = _as_client_error(e)
        logger.error(
            "[%s] %s persist failed: %s",
            body.device_id,
            body.action.value,
            err.detail or err,
        )
        _emit_cmd_ack(
            cfg,
            ref_msg_id=header.msg_id,
            device_id=body.device_id,
            action=body.action,
            code=ClientErrorCode.CONFIG_SAVE_FAILED,
            reason=err.code.value,
        )
        return

    with slot.lock:
        slot.device = new_device
        if reload_client:
            slot.reload.set()

    logger.info(
        "[%s] %s applied addrs=%s period_ms=%s reload=%s",
        body.device_id,
        body.action.value,
        new_device.scan_addresses,
        new_device.scan_period_ms,
        reload_client,
    )
    _emit_cmd_ack(
        cfg,
        ref_msg_id=header.msg_id,
        device_id=body.device_id,
        action=body.action,
    )


def _apply_set_scan(
    cfg: Settings,
    slots: dict[str, DeviceSlot],
    slot: DeviceSlot,
    header: ProtocolHeaderDTO,
    body: MsgCmdRDTO,
) -> None:
    """스캔 주소/주기만 반영한다 (재연결 없음)."""
    if body.d_address is None and body.period_ms is None:
        _emit_cmd_ack(
            cfg,
            ref_msg_id=header.msg_id,
            device_id=body.device_id,
            action=body.action,
            code=ClientErrorCode.CMD_FIELD_MISSING,
            reason="d_address/period_ms 없음",
        )
        return

    with slot.lock:
        data = slot.device.model_dump(mode="json")
    if body.d_address is not None:
        data["scan_addresses"] = list(body.d_address)
    if body.period_ms is not None:
        data["scan_period_ms"] = body.period_ms

    _commit_device(cfg, slots, slot, header, body, data, reload_client=False)


def _apply_set_device(
    cfg: Settings,
    slots: dict[str, DeviceSlot],
    slot: DeviceSlot,
    header: ProtocolHeaderDTO,
    body: MsgCmdRDTO,
) -> None:
    """전체 DeviceSettings를 반영하고 close→rebuild를 요청한다."""
    if not body.device_setup:
        _emit_cmd_ack(
            cfg,
            ref_msg_id=header.msg_id,
            device_id=body.device_id,
            action=body.action,
            code=ClientErrorCode.CMD_FIELD_MISSING,
            reason="device_setup 없음",
        )
        return

    _commit_device(
        cfg,
        slots,
        slot,
        header,
        body,
        dict(body.device_setup),
        reload_client=True,
    )


def _emit_body_invalid_ack(cfg: Settings, header: ProtocolHeaderDTO) -> None:
    """본문 파싱 실패 ACK. action조차 못 읽으면 로그만 남긴다."""
    raw_action = (header.msg_body or {}).get("action")
    try:
        action = MsgCmdREnum(raw_action)
    except ValueError:
        logger.warning("cmd_r action 판별 불가, ack 생략: %r", raw_action)
        return
    _emit_cmd_ack(
        cfg,
        ref_msg_id=header.msg_id,
        device_id=header.collector_address,
        action=action,
        code=ClientErrorCode.CMD_BODY_INVALID,
    )


def _handle_cmd_r(
    cfg: Settings,
    slots: dict[str, DeviceSlot],
    header: ProtocolHeaderDTO,
) -> None:
    """cmd_r 공통 검증 후 SET_SCAN / SET_DEVICE만 처리한다."""
    try:
        body = MsgCmdRDTO.model_validate(header.msg_body)
    except ValidationError as e:
        logger.warning("cmd_r body invalid: %s", e)
        _emit_body_invalid_ack(cfg, header)
        return

    if body.device_id != header.collector_address:
        logger.warning(
            "cmd_r device_id 불일치: topic=%s body=%s",
            header.collector_address,
            body.device_id,
        )
        _emit_cmd_ack(
            cfg,
            ref_msg_id=header.msg_id,
            device_id=header.collector_address,
            action=body.action,
            code=ClientErrorCode.CMD_DEVICE_MISMATCH,
            reason=f"body.device_id={body.device_id}",
        )
        return

    slot = slots.get(body.device_id)
    if slot is None:
        _emit_cmd_ack(
            cfg,
            ref_msg_id=header.msg_id,
            device_id=body.device_id,
            action=body.action,
            code=ClientErrorCode.CMD_UNKNOWN_DEVICE,
        )
        return

    if body.action is MsgCmdREnum.SET_SCAN:
        _apply_set_scan(cfg, slots, slot, header, body)
        return
    if body.action is MsgCmdREnum.SET_DEVICE:
        _apply_set_device(cfg, slots, slot, header, body)
        return

    logger.info(
        "[%s] cmd_r action not implemented: %s",
        body.device_id,
        body.action.value,
    )
    _emit_cmd_ack(
        cfg,
        ref_msg_id=header.msg_id,
        device_id=body.device_id,
        action=body.action,
        code=ClientErrorCode.CMD_UNSUPPORTED_ACTION,
    )


def _dispatch_sub(
    cfg: Settings,
    slots: dict[str, DeviceSlot],
    header: ProtocolHeaderDTO,
) -> None:
    """SUB로 받은 헤더를 로그하고, 구현된 타입만 처리한다."""
    # DATA/HEALTH/ACK PUB와 동일하게 전문을 INFO로 남긴다 (수신 경로)
    logger.info(
        "[SUB %s] %s",
        header.msg_type.value.upper(),
        header.model_dump_json(),
    )

    if header.msg_type is MsgTypeEnum.CMD_R:
        _handle_cmd_r(cfg, slots, header)
        return
    if header.msg_type is MsgTypeEnum.CMD_W:
        # 처리 로직은 아직 없음 — 수신 로그만
        return
    if header.msg_type in (MsgTypeEnum.ACK, MsgTypeEnum.HEALTH):
        # collector는 보통 PUB만 하지만, SUB로 들어오면 로그만
        return
    logger.debug("sub ignore msg_type=%s", header.msg_type.value)


def run_device(cfg: Settings, slot: DeviceSlot) -> None:
    """단일 디바이스의 연결·스캔·재연결·설정 리로드 루프를 돌린다."""
    reconnect_s = cfg.app.reconnect_period_ms / 1000.0
    with slot.lock:
        device = slot.device.model_copy(deep=True)
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
            with slot.lock:
                device = slot.device.model_copy(deep=True)
                slot.reload.clear()

            if not ensure_connected(cfg, device, client, reconnect_s):
                break

            while _running:
                if slot.reload.is_set():
                    logger.info("[%s] reloading client settings", device.id)
                    _safe_close(client)
                    with slot.lock:
                        device = slot.device.model_copy(deep=True)
                        slot.reload.clear()
                    client = build_client(device)
                    break

                with slot.lock:
                    device = slot.device.model_copy(deep=True)
                period_s = device.scan_period_ms / 1000.0

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
                    _sleep_interruptible(remain, wake=slot.reload)
    finally:
        _safe_close(client)
        logger.info("[%s] worker stop", device.id)


def run(cfg: Settings | None = None) -> None:
    """ZeroMQ를 열고 디바이스 워커·SUB 디스패치를 돌린다."""
    global _running, _zmq
    cfg = cfg or settings
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    slots = {d.id: DeviceSlot(device=d) for d in cfg.devices}

    logger.info(
        "daemon start devices=%s reconnect_ms=%s",
        list(slots.keys()),
        cfg.app.reconnect_period_ms,
    )

    zmq = ZeroMqClient(
        cfg.app.zmq,
        device_ids=list(slots.keys()),
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
            args=(cfg, slot),
            name=f"plc-{device_id}",
            daemon=True,
        )
        for device_id, slot in slots.items()
    ]
    for t in threads:
        t.start()

    try:
        while _running:
            try:
                header = zmq.recv()
            except Exception as e:
                err = _as_client_error(e)
                logger.warning(
                    "zmq sub failed: %s(%s) %s",
                    err.code.value,
                    err.code.label,
                    err.detail or err,
                )
                _sleep_interruptible(0.2)
                continue
            if header is None:
                continue
            try:
                _dispatch_sub(cfg, slots, header)
            except Exception as e:
                err = _as_client_error(e)
                logger.error(
                    "cmd dispatch failed: %s(%s) %s",
                    err.code.value,
                    err.code.label,
                    err.detail or err,
                )
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
