from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from pylabrecorder.utils.logs import logger

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


@pytest.fixture
def is_editable_install() -> None:
    """Skip the test if pylabrecorder is not installed in editable mode."""
    origin = Path(find_spec("pylabrecorder").origin)
    for folder in origin.parents[1:3]:  # support 'src' or 'flat' layout structure
        if (folder / "pyproject.toml").exists():
            return
    pytest.skip("pylabrecorder is not installed in editable mode.")
