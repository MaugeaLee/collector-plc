"""프로젝트 진입점. daemon 스캔 루프를 시작한다."""

from daemon import run as run_daemon
from utils.logging_setup import setup_logging


def main():
    setup_logging()
    run_daemon()


if __name__ == "__main__":
    main()
