"""
Smoke tests: the package imports and the ``mailvigil`` entry point answers.

No isolation is needed yet: ``--version`` reads no files and touches no network.
"""

from __future__ import annotations

import importlib
from importlib.metadata import PackageNotFoundError

import pytest

import mailvigil
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


def test_unknown_flag_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown flag exits with 2 and the usage error goes to stderr, never to stdout."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--nope"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "usage:" in captured.err
    assert captured.out == ""


def test_version_falls_back_without_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without installed metadata the version falls back to the development placeholder."""

    def missing(distribution_name: str) -> str:
        raise PackageNotFoundError(distribution_name)

    monkeypatch.setattr("importlib.metadata.version", missing)
    try:
        importlib.reload(mailvigil)
        assert mailvigil.__version__ == "0.0.0.dev0"
    finally:
        # why: reload again with the real lookup so the other tests see the installed version
        monkeypatch.undo()
        importlib.reload(mailvigil)
