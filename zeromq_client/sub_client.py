"""게이트웨이 CMD를 받는 SUB 클라이언트."""

from __future__ import annotations

import logging

import zmq
from pydantic import ValidationError

from client.errors import ClientError, to_client_error
from model.error_model import ClientErrorCode
from model.protocol_model import ProtocolHeaderDTO
from zeromq_client.base_client import BaseZmqClient

logger = logging.getLogger(__name__)


class ZmqSubClient(BaseZmqClient):
    """[topic, json] multipart SUB. 타임아웃 시 None."""

    socket_type = zmq.SUB

    def __init__(
        self,
        endpoint: str,
        *,
        bind: bool = False,
        linger_ms: int = 0,
        topics: list[str] | None = None,
        recv_timeout_ms: int = 100,
    ):
        super().__init__(endpoint, bind=bind, linger_ms=linger_ms)
        # topics=[] / None → 전부 구독("")
        self.topics = topics if topics is not None else [""]
        self.recv_timeout_ms = recv_timeout_ms

    def _configure_socket(self, sock: zmq.Socket) -> None:
        sock.setsockopt(zmq.RCVTIMEO, self.recv_timeout_ms)
        for topic in self.topics:
            sock.setsockopt_string(zmq.SUBSCRIBE, topic)

    def recv(self, timeout_ms: int | None = None) -> ProtocolHeaderDTO | None:
        """한 건 수신. 타임아웃이면 None, 프로토콜 오류는 ClientError."""
        if timeout_ms is not None:
            self.sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        try:
            frames = self.sock.recv_multipart()
        except zmq.Again:
            return None
        except Exception as e:
            raise to_client_error(
                e, default=ClientErrorCode.READ_FAILED
            ) from e
        finally:
            if timeout_ms is not None:
                self.sock.setsockopt(zmq.RCVTIMEO, self.recv_timeout_ms)

        if len(frames) < 2:
            raise ClientError(
                ClientErrorCode.PROTOCOL_ERROR,
                f"multipart 프레임 부족: {len(frames)}",
            )

        raw = frames[-1]
        try:
            header = ProtocolHeaderDTO.model_validate_json(raw)
        except ValidationError as e:
            raise ClientError(
                ClientErrorCode.PROTOCOL_ERROR,
                f"ProtocolHeaderDTO 파싱 실패: {e}",
            ) from e

        logger.debug(
            "zmq sub [%s] %s",
            frames[0].decode("utf-8", errors="replace"),
            header.msg_type.value,
        )
        return header
