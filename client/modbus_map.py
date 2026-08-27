"""Modbus(TCP/RTU)용 D/R 주소 → 레지스터 인덱스·함수코드 변환."""

from __future__ import annotations

from typing import Literal

from client.errors import ClientError
from model.client_model import ModbusMapSettings
from model.error_model import ClientErrorCode

RegisterKind = Literal["holding", "input"]

# Modbus 경로에서 워드.비트를 지원하는 디바이스
_MODBUS_WORD_DEVICES = frozenset({"D", "R"})


class ModbusRegisterSpec:
    """PLC 주소 한 건에 대응하는 Modbus 읽기/쓰기 위치."""

    __slots__ = ("register_kind", "index", "plc_kind", "plc_num")

    def __init__(
        self,
        *,
        register_kind: RegisterKind,
        index: int,
        plc_kind: str,
        plc_num: int,
    ):
        self.register_kind = register_kind
        self.index = index
        self.plc_kind = plc_kind
        self.plc_num = plc_num


def resolve_modbus_register(
    kind: str,
    num: int,
    settings: ModbusMapSettings,
) -> ModbusRegisterSpec:
    """PLC 디바이스·번지를 Modbus 레지스터 인덱스(0-based)로 변환한다.

    D{n} → Holding/Input 중 d_register_type, index = n - modbus_d_register_start
    R{n} → r_register_type, index = n - modbus_r_register_start
    """
    kind = kind.upper()
    if kind == "D":
        index = num - settings.modbus_d_register_start
        if index < 0:
            raise ClientError(
                ClientErrorCode.ADDR_OUT_OF_RANGE,
                f"D{num} < modbus_d_register_start({settings.modbus_d_register_start})",
            )
        return ModbusRegisterSpec(
            register_kind=settings.modbus_d_register_type,
            index=index,
            plc_kind=kind,
            plc_num=num,
        )
    if kind == "R":
        if settings.modbus_r_register_start is None:
            raise ClientError(
                ClientErrorCode.UNSUPPORTED_ADDR,
                f"R 주소는 modbus_r_register_start 미설정: {kind}{num}",
            )
        index = num - settings.modbus_r_register_start
        if index < 0:
            raise ClientError(
                ClientErrorCode.ADDR_OUT_OF_RANGE,
                f"R{num} < modbus_r_register_start({settings.modbus_r_register_start})",
            )
        return ModbusRegisterSpec(
            register_kind=settings.modbus_r_register_type,
            index=index,
            plc_kind=kind,
            plc_num=num,
        )
    raise ClientError(
        ClientErrorCode.UNSUPPORTED_ADDR,
        f"Modbus는 D/R 워드만 지원: {kind}{num}",
    )


def assert_modbus_word_device(kind: str, addr: str) -> None:
    """워드.비트 접미가 붙은 주소의 디바이스 종류를 검증한다."""
    if kind.upper() not in _MODBUS_WORD_DEVICES:
        raise ClientError(
            ClientErrorCode.UNSUPPORTED_ADDR,
            f"비트 표기는 D/R 워드만 지원: {addr}",
        )
