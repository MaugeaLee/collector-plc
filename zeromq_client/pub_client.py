"""게이트웨이로 ProtocolHeaderDTO를 보내는 PUB 클라이언트."""

from __future__ import annotations

import logging

import zmq

from client.errors import ClientError, to_client_error
from model.error_model import ClientErrorCode
from model.protocol_model import ProtocolHeaderDTO
from zeromq_client.base_client import BaseZmqClient

logger = logging.getLogger(__name__)


class ZmqPubClient(BaseZmqClient):
    """[topic, json] multipart PUB."""

    socket_type = zmq.PUB

    def __init__(
        self,
        endpoint: str,
        *,
        bind: bool = True,
        linger_ms: int = 0,
        topic: str = "",
    ):
        super().__init__(endpoint, bind=bind, linger_ms=linger_ms)
        self.topic = topic

    def send(self, header: ProtocolHeaderDTO, *, topic: str | None = None) -> None:
        """ProtocolHeaderDTO를 JSON multipart로 송신한다."""
        t = (topic if topic is not None else self.topic).encode("utf-8")
        payload = header.model_dump_json().encode("utf-8")
        try:
            self.sock.send_multipart([t, payload], flags=zmq.NOBLOCK)
        except zmq.Again as e:
            raise ClientError(
                ClientErrorCode.TIMEOUT,
                f"PUB 송신 버퍼 full: {self._target()}",
            ) from e
        except Exception as e:
            raise to_client_error(
                e, default=ClientErrorCode.WRITE_FAILED
            ) from e
        logger.debug(
            "zmq pub [%s] %s",
            (topic if topic is not None else self.topic) or "-",
            header.msg_type.value,
        )
