"""게이트웨이 IPC용 PUB+SUB 파사드."""

from __future__ import annotations

import logging
import threading

from model.client_model import ZmqSettings
from model.protocol_model import ProtocolHeaderDTO
from zeromq_client.pub_client import ZmqPubClient
from zeromq_client.sub_client import ZmqSubClient
from zeromq_client.topics import cmd_subscribe_prefix, topic_for

logger = logging.getLogger(__name__)


class ZeroMqClient:
    """
    collector → gateway: PUB (data / health / ack)
    gateway → collector: SUB (cmd_r / cmd_w)

    토픽: collector.plc.{devices[].device_key}.{msg_type}
    """

    def __init__(self, settings: ZmqSettings, *, device_ids: list[str]):
        self.settings = settings
        self.device_ids = list(device_ids)
        # PUB(워커 스레드)와 SUB(메인 스레드)는 소켓이 다르다.
        # 한 lock으로 recv까지 감싸면 SUB 대기 동안 DATA PUB이 전부 멈춘다.
        self._pub_lock = threading.Lock()
        self._sub_lock = threading.Lock()
        self._pub = ZmqPubClient(
            settings.pub_endpoint,
            bind=settings.pub_bind,
            linger_ms=settings.linger_ms,
        )
        self._sub = ZmqSubClient(
            settings.sub_endpoint,
            bind=settings.sub_bind,
            linger_ms=settings.linger_ms,
            topics=[cmd_subscribe_prefix(d) for d in self.device_ids],
            recv_timeout_ms=settings.recv_timeout_ms,
        )

    def connect(self) -> None:
        self._pub.connect()
        try:
            self._sub.connect()
        except Exception:
            self._pub.close()
            raise
        logger.info(
            "ZeroMQ ready pub=%s(%s) sub=%s(%s) devices=%s",
            self.settings.pub_endpoint,
            "bind" if self.settings.pub_bind else "connect",
            self.settings.sub_endpoint,
            "bind" if self.settings.sub_bind else "connect",
            self.device_ids,
        )

    def close(self) -> None:
        with self._pub_lock:
            self._pub.close()
        with self._sub_lock:
            self._sub.close()

    def send(self, header: ProtocolHeaderDTO, *, topic: str | None = None) -> None:
        t = topic if topic is not None else topic_for(
            header.collector_address, header.msg_type
        )
        with self._pub_lock:
            self._pub.send(header, topic=t)

    def recv(self, timeout_ms: int | None = None) -> ProtocolHeaderDTO | None:
        with self._sub_lock:
            return self._sub.recv(timeout_ms=timeout_ms)
