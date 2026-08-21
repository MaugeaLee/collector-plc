"""
collector에 cmd_r(SET_SCAN / SET_DEVICE)를 보내는 스모크 테스트.

collector: ZMQ_SUB_ENDPOINT 에 connect(SUB)
이 스크립트: 같은 엔드포인트에 bind(PUB)  ← 게이트웨이 임시 역할

사용 (프로젝트 루트, collector 실행 중):
    python tester/send_config.py set-scan plc-mitsubishi-1 --addrs D100,M10 --period 500
    python tester/send_config.py set-device plc-mitsubishi-1 --period 2000
    python tester/send_config.py set-device plc-mitsubishi-1 --host 127.0.0.1 --port 5000

주의: collector가 5556에 붙을 시간을 준 뒤 보내고, ACK 올 때까지 PUB를 유지한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import zmq
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PUB_ENDPOINT = os.getenv("ZMQ_PUB_ENDPOINT", "tcp://127.0.0.1:5555").strip()
SUB_ENDPOINT = os.getenv("ZMQ_SUB_ENDPOINT", "tcp://127.0.0.1:5556").strip()
GATEWAY_ADDRESS = os.getenv("GATEWAY_ADDRESS", "gateway").strip()
PLC_CONFIG = Path(
    os.getenv("PLC_CONFIG_FILE", "plc_setting.json").strip()
)
if not PLC_CONFIG.is_absolute():
    PLC_CONFIG = ROOT / PLC_CONFIG

# bind 후 collector SUB가 붙을 때까지 대기
DEFAULT_JOIN_S = 1.5
# 같은 cmd 재전송 간격
DEFAULT_RESEND_S = 0.5


def _now_ms() -> int:
    return int(time.time() * 1000)


def _load_device(device_id: str) -> dict:
    data = json.loads(PLC_CONFIG.read_text(encoding="utf-8"))
    devices = data.get("devices") or []
    for d in devices:
        if d.get("id") == device_id:
            return dict(d)
    raise SystemExit(f"device not found in {PLC_CONFIG}: {device_id}")


def _topic(device_id: str) -> str:
    return f"collector.plc.{device_id}.cmd_r"


def _header(device_id: str, body: dict) -> dict:
    return {
        "msg_id": str(uuid4()),
        "gateway_address": GATEWAY_ADDRESS,
        "collector_address": device_id,
        "msg_type": "cmd_r",
        "msg_body": body,
        "timestamp_ms": _now_ms(),
    }


def _send_and_wait_ack(
    device_id: str,
    body: dict,
    *,
    wait_s: float,
    join_s: float = DEFAULT_JOIN_S,
    resend_s: float = DEFAULT_RESEND_S,
) -> None:
    """
    5556 bind → collector 접속 대기 → 전송.
    ACK를 받기 전까지 PUB를 닫지 않고, 같은 메시지를 주기적으로 다시 보낸다.
    """
    topic = _topic(device_id)
    header = _header(device_id, body)
    payload = json.dumps(header, ensure_ascii=False).encode("utf-8")
    topic_b = topic.encode("utf-8")

    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.setsockopt(zmq.LINGER, 0)
    pub.bind(SUB_ENDPOINT)

    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt(zmq.RCVTIMEO, 200)
    sub.setsockopt_string(zmq.SUBSCRIBE, f"collector.plc.{device_id}.ack")
    sub.connect(PUB_ENDPOINT)

    print(
        f"PUB bind={SUB_ENDPOINT}  "
        f"collector 접속 대기 {join_s:.1f}s 후 전송 "
        f"(ACK까지 소켓 유지, {resend_s:.1f}s마다 재전송)"
    )
    time.sleep(max(0.0, join_s))

    print(f"send topic={topic}")
    print(json.dumps(header, ensure_ascii=False, indent=2))

    deadline = time.monotonic() + max(1.0, wait_s)
    ref = header["msg_id"]
    next_send = 0.0
    sent = 0
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                pub.send_multipart([topic_b, payload])
                sent += 1
                next_send = now + max(0.1, resend_s)
                print(f"... sent #{sent} (waiting ack)")

            try:
                frames = sub.recv_multipart()
            except zmq.Again:
                continue
            if len(frames) < 2:
                continue
            raw = frames[-1].decode("utf-8", errors="replace")
            try:
                ack = json.loads(raw)
            except json.JSONDecodeError:
                print(f"ack raw: {raw}")
                continue
            body_ack = ack.get("msg_body") or {}
            if str(body_ack.get("ref_msg_id")) != ref:
                continue
            print("\nack:")
            print(json.dumps(ack, ensure_ascii=False, indent=2))
            return

        print(
            f"\n(no ack within {wait_s}s, sent={sent})\n"
            "collector 실행 중인지, 5556에 다른 PUB bind가 없는지 확인"
        )
        raise SystemExit(2)
    finally:
        pub.close(linger=0)
        sub.close(linger=0)


def cmd_set_scan(args: argparse.Namespace) -> None:
    addrs = [a.strip() for a in args.addrs.split(",") if a.strip()]
    body: dict = {
        "device_id": args.device_id,
        "action": "SET_SCAN",
        "deadline_ms": _now_ms() + 10_000,
    }
    if addrs:
        body["d_address"] = addrs
    if args.period is not None:
        body["period_ms"] = args.period
    if "d_address" not in body and "period_ms" not in body:
        raise SystemExit("SET_SCAN: --addrs 또는 --period 필요")
    _send_and_wait_ack(
        args.device_id,
        body,
        wait_s=args.wait,
        join_s=args.join,
        resend_s=args.resend,
    )


def cmd_set_device(args: argparse.Namespace) -> None:
    device = _load_device(args.device_id)
    if args.host is not None:
        device["host"] = args.host
    if args.port is not None:
        device["port"] = args.port
    if args.period is not None:
        device["scan_period_ms"] = args.period
    if args.addrs:
        device["scan_addresses"] = [
            a.strip() for a in args.addrs.split(",") if a.strip()
        ]
    if args.timeout is not None:
        device["timeout"] = args.timeout

    body = {
        "device_id": args.device_id,
        "action": "SET_DEVICE",
        "device_setup": device,
        "deadline_ms": _now_ms() + 10_000,
    }
    _send_and_wait_ack(
        args.device_id,
        body,
        wait_s=args.wait,
        join_s=args.join,
        resend_s=args.resend,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="collector cmd_r config 테스트")
    p.add_argument(
        "--wait",
        type=float,
        default=8.0,
        help="ACK 대기 초 (기본 8, 그동안 PUB 유지·재전송)",
    )
    p.add_argument(
        "--join",
        type=float,
        default=DEFAULT_JOIN_S,
        help=f"bind 후 첫 전송까지 대기 초 (기본 {DEFAULT_JOIN_S})",
    )
    p.add_argument(
        "--resend",
        type=float,
        default=DEFAULT_RESEND_S,
        help=f"재전송 간격 초 (기본 {DEFAULT_RESEND_S})",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("set-scan", help="SET_SCAN (재연결 없음)")
    scan.add_argument("device_id")
    scan.add_argument(
        "--addrs",
        default="",
        help="콤마 구분 주소 (예: D100,M10)",
    )
    scan.add_argument("--period", type=int, default=None, help="scan_period_ms")
    scan.set_defaults(func=cmd_set_scan)

    device = sub.add_parser(
        "set-device",
        help="SET_DEVICE (plc_setting.json 기준 + 옵션 덮어쓰기, 재연결)",
    )
    device.add_argument("device_id")
    device.add_argument("--host", default=None)
    device.add_argument("--port", type=int, default=None)
    device.add_argument("--period", type=int, default=None)
    device.add_argument("--addrs", default="", help="콤마 구분 scan_addresses")
    device.add_argument("--timeout", type=float, default=None)
    device.set_defaults(func=cmd_set_device)

    return p


def main() -> None:
    args = build_parser().parse_args()
    print(f"cmd PUB bind={SUB_ENDPOINT}  ack SUB connect={PUB_ENDPOINT}")
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
