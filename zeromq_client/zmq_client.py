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

    토픽: collector.plc.{collector_address}.{msg_type}
    """

    def __init__(self, settings: ZmqSettings, *, collector_address: str):
        self.settings = settings
        self.collector_address = collector_address
        self._lock = threading.Lock()
        self._pub = ZmqPubClient(
            settings.pub_endpoint,
            bind=settings.pub_bind,
            linger_ms=settings.linger_ms,
        )
        self._sub = ZmqSubClient(
            settings.sub_endpoint,
            bind=settings.sub_bind,
            linger_ms=settings.linger_ms,
            topic=cmd_subscribe_prefix(collector_address),
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
            "ZeroMQ ready pub=%s(%s) sub=%s(%s) sub_topic=%s",
            self.settings.pub_endpoint,
            "bind" if self.settings.pub_bind else "connect",
            self.settings.sub_endpoint,
            "bind" if self.settings.sub_bind else "connect",
            cmd_subscribe_prefix(self.collector_address),
        )

    def close(self) -> None:
        with self._lock:
            self._pub.close()
            self._sub.close()

    def send(self, header: ProtocolHeaderDTO, *, topic: str | None = None) -> None:
        t = topic if topic is not None else topic_for(
            self.collector_address, header.msg_type
        )
        with self._lock:
            self._pub.send(header, topic=t)

    def recv(self, timeout_ms: int | None = None) -> ProtocolHeaderDTO | None:
        with self._lock:
            return self._sub.recv(timeout_ms=timeout_ms)
