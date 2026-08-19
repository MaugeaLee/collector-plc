"""
PLC 통신 테스트 진입점.

.env의 PLC_MODE(tcp|rtu)에 따라 클라이언트를 만들고 연결만 확인한다.
실제 읽기/쓰기는 각 클라이언트 파일을 직접 수정해서 실험하면 된다.
"""

import config
from client.rtu_client import RtuClient
from client.tcp_client import TcpClient


def main():
    if config.PLC_MODE == "tcp":
        client = TcpClient()
    elif config.PLC_MODE == "rtu":
        client = RtuClient()
    else:
        raise ValueError(f"알 수 없는 PLC_MODE: {config.PLC_MODE} (tcp 또는 rtu)")

    print(f"mode={config.PLC_MODE} target={client._target()} 연결 시도")
    try:
        client.connect()
        print("연결 성공")
        # 예: values = client.read_holding_registers(0, count=1)
        # print(values)
    finally:
        client.close()
        print("종료")


if __name__ == "__main__":
    main()
