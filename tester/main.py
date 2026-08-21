"""
collector(main.py) PUB 수신 스모크 테스트.

사용 (프로젝트 루트에서):
    python tester/main.py

collector가 ZMQ_PUB_ENDPOINT에 bind한 뒤 실행한다.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import zmq
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PUB_ENDPOINT = os.getenv("ZMQ_PUB_ENDPOINT", "tcp://127.0.0.1:5555").strip()
# devices[].id 별 토픽 → collector.plc.* 전부 수신
TOPIC_PREFIX = "collector.plc."


def main() -> None:
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, 1000)
    sock.setsockopt_string(zmq.SUBSCRIBE, TOPIC_PREFIX)
    sock.connect(PUB_ENDPOINT)

    print(f"listening connect={PUB_ENDPOINT} topic={TOPIC_PREFIX!r} (Ctrl+C 종료)")
    # PUB slow joiner: 구독 직후 잠깐 대기
    time.sleep(0.5)

    try:
        while True:
            try:
                frames = sock.recv_multipart()
            except zmq.Again:
                continue
            if len(frames) < 2:
                print(f"bad frames: {len(frames)}")
                continue
            topic = frames[0].decode("utf-8", errors="replace")
            raw = frames[-1].decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
                print(f"\n[{topic}]")
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                print(f"\n[{topic}] (raw) {raw}")
    except KeyboardInterrupt:
        print("\nstop")
    finally:
        sock.close(linger=0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
