from __future__ import annotations

import pytest
from click.testing import CliRunner

from pylabrecorder._commands.sys_info import run


def test_sys_info() -> None:
    """Test the system information entry-point."""
    runner = CliRunner()
    result = runner.invoke(run)
    assert result.exit_code == 0
    assert "Platform:" in result.output
    assert "Python:" in result.output
    assert "Executable:" in result.output
    assert "Core dependencies" in result.output


@pytest.mark.usefixtures("is_editable_install")
def test_sys_info_developer() -> None:
    """Test the system information entry-point with developer dependencies."""
    runner = CliRunner()
    result = runner.invoke(run, ["--developer"])
    assert result.exit_code == 0
    assert "Platform:" in result.output
    assert "Python:" in result.output
    assert "Executable:" in result.output
    assert "Core dependencies" in result.output
    assert "Developer 'style' dependencies" in result.output
    assert "Developer 'test' dependencies" in result.output
