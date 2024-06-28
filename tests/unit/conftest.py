# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=duplicate-code,missing-function-docstring

"""Unit test fixtures."""

import pathlib
import typing
from unittest.mock import patch

import ops.testing
import pytest

import keychain
from charm import ChronyCharm


@pytest.fixture
def harness(  # pylint: disable=too-many-locals
    tmp_path_factory,
) -> typing.Generator[ops.testing.Harness, None, None]:
    """Create ops.testing.Harness object and patch necessary functions in code."""
    mock_config = ""

    def read_config():
        return mock_config

    def write_config(config: str):
        nonlocal mock_config
        mock_config = config

    certs: dict[str, str] = {}

    def _iter_certs_dir():
        for file in certs:
            yield pathlib.Path("/etc/chrony/certs") / file

    def _write_certs_file(path: pathlib.Path, content: str):
        certs[path.name] = content

    def _read_certs_file(path: pathlib.Path):
        return certs[path.name]

    def _unlink_certs_file(path: pathlib.Path) -> None:
        del certs[path.name]

    var_lib_chrony = tmp_path_factory.mktemp("var_lib_chrony")

    with (
        patch("chrony.Chrony.install"),
        patch("chrony.Chrony.restart"),
        patch("chrony.Chrony.write_config") as mock_write_config,
        patch("chrony.Chrony.read_config") as mock_read_config,
        patch("chrony.Chrony._make_certs_dir"),
        patch("chrony.Chrony._iter_certs_dir") as mock_iter_certs_dir,
        patch("chrony.Chrony._write_certs_file") as mock_write_certs_file,
        patch("chrony.Chrony._read_certs_file") as mock_read_certs_file,
        patch("chrony.Chrony._unlink_certs_file") as mock_unlink_certs_file,
        patch.object(keychain.TlsKeychain, "STORAGE_DIR", var_lib_chrony / "tls-keychain"),
    ):
        mock_read_config.side_effect = read_config
        mock_write_config.side_effect = write_config
        mock_iter_certs_dir.side_effect = _iter_certs_dir
        mock_write_certs_file.side_effect = _write_certs_file
        mock_read_certs_file.side_effect = _read_certs_file
        mock_unlink_certs_file.side_effect = _unlink_certs_file
        yield ops.testing.Harness(ChronyCharm)
