"""
Smoke tests: the package imports and the ``mailvigil`` entry point answers.

No isolation is needed yet: ``--version`` reads no files and touches no network.
"""

from __future__ import annotations

import pytest

from mailvigil import __version__
from mailvigil.cli import main


def test_version_is_exposed() -> None:
    """The package exposes a non-empty version string."""
    assert __version__


def test_version_flag_prints_version_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """``mailvigil --version`` prints the program name and version, then exits with 0."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"mailvigil {__version__}"


def test_no_arguments_exits_zero() -> None:
    """Without arguments the skeleton command does nothing and succeeds."""
    assert main([]) == 0
