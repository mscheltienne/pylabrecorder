from __future__ import annotations

import os
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from pylabrecorder.utils.logs import logger

if TYPE_CHECKING:
    import pytest


lsl_cfg = NamedTemporaryFile("w", prefix="lsl", suffix=".cfg", delete=False)
if "LSLAPICFG" not in os.environ:
    with lsl_cfg as fid:
        fid.write("[log]\nlevel = -2\n\n[multicast]\nResolveScope = link")
    os.environ["LSLAPICFG"] = lsl_cfg.name


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest options."""
    logger.propagate = True


def pytest_sessionfinish(session, exitstatus) -> None:
    """Clean up the pytest session."""
    try:
        os.unlink(lsl_cfg.name)
    except Exception:
        pass
