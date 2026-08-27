"""PLC 주소 문자열 파싱·워드 내 비트 연산."""

from __future__ import annotations

import re

from client.errors import ClientError
from model.error_model import ClientErrorCode

# D100 / ZR10 / D100.5 / D800.A (워드.비트, 비트 0–15 — 10–15는 A–F)
_ADDR_RE = re.compile(r"^([A-Za-z]+)(\d+)(?:\.([0-9A-Fa-f]+))?$")
WORD_BIT_MAX = 15


def _parse_bit_index(bit_raw: str, addr: str) -> int:
    """워드.비트 접미: 0–9(10진), A–F(16진, 비트 10–15)."""
    if bit_raw.isdecimal():
        bit = int(bit_raw, 10)
    elif len(bit_raw) == 1 and bit_raw.upper() in "ABCDEF":
        bit = int(bit_raw, 16)
    else:
        raise ClientError(
            ClientErrorCode.UNSUPPORTED_ADDR,
            f"비트 인덱스는 0–9 또는 A–F: {addr}",
        )
    if bit < 0 or bit > WORD_BIT_MAX:
        raise ClientError(
            ClientErrorCode.UNSUPPORTED_ADDR,
            f"비트 인덱스는 0–{WORD_BIT_MAX}: {addr}",
        )
    return bit


def parse_plc_addr(addr: str) -> tuple[str, int, int | None]:
    """'D100' / 'D100.5' / 'D800.A' / 'ZR10' → (디바이스, 번호, 비트|None)."""
    m = _ADDR_RE.match(addr.strip())
    if not m:
        raise ClientError(
            ClientErrorCode.UNSUPPORTED_ADDR,
            f"지원하지 않는 주소 형식: {addr}",
        )
    kind = m.group(1).upper()
    num = int(m.group(2))
    bit_raw = m.group(3)
    if bit_raw is None:
        return kind, num, None
    return kind, num, _parse_bit_index(bit_raw, addr)


def extract_word_bit(word: int, bit: int) -> int:
    """16비트 워드에서 bit 위치(0–15)의 값을 0/1로 반환한다."""
    return (int(word) >> bit) & 1


def apply_word_bit(word: int, bit: int, value: int) -> int:
    """워드의 bit 위치를 value(0/1)로 바꾼 16비트 값을 반환한다."""
    w = int(word) & 0xFFFF
    if int(value):
        return w | (1 << bit)
    return w & ~(1 << bit) & 0xFFFF
