"""로깅 기본 셋업. main에서 한 번만 호출하면 된다."""

from __future__ import annotations

import logging
import sys

from config import settings


def setup_logging() -> None:
    level = getattr(logging, settings.app.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
