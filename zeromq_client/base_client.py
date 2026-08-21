"""ZeroMQ 소켓 공통: Context, bind/connect, close."""

from __future__ import annotations

import logging

import zmq

from client.errors import ClientError, to_client_error
from model.error_model import ClientErrorCode

logger = logging.getLogger(__name__)


class BaseZmqClient:
    """단일 소켓(PUB/SUB 등)의 수명주기."""

    socket_type: int

    def __init__(self, endpoint: str, *, bind: bool, linger_ms: int = 0):
        self.endpoint = endpoint
        self.bind = bind
        self.linger_ms = linger_ms
        self._ctx: zmq.Context | None = None
        self._sock: zmq.Socket | None = None

    @property
    def sock(self) -> zmq.Socket:
        if self._sock is None:
            raise ClientError(
                ClientErrorCode.CONNECT_FAILED,
                f"소켓 미연결: {self._target()}",
            )
        return self._sock

    def _target(self) -> str:
        mode = "bind" if self.bind else "connect"
        return f"{mode}:{self.endpoint}"

    def connect(self) -> None:
        try:
            self._ctx = zmq.Context.instance()
            self._sock = self._ctx.socket(self.socket_type)
            self._sock.setsockopt(zmq.LINGER, self.linger_ms)
            self._configure_socket(self._sock)
            if self.bind:
                self._sock.bind(self.endpoint)
            else:
                self._sock.connect(self.endpoint)
        except Exception as e:
            self.close()
            raise to_client_error(
                e, default=ClientErrorCode.CONNECT_FAILED
            ) from e
        logger.debug("zmq connected: %s type=%s", self._target(), self.socket_type)

    def _configure_socket(self, sock: zmq.Socket) -> None:
        """서브클래스에서 RCVTIMEO·구독 토픽 등 설정."""

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            sock.close(linger=self.linger_ms)
        except Exception as e:
            logger.debug("zmq close failed: %s", e)
