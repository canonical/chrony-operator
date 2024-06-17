# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=duplicate-code,missing-function-docstring

"""Unit test fixtures."""
import typing
from unittest.mock import patch

import ops.testing
import pytest

from src.charm import ChronyCharm


@pytest.fixture
def harness() -> typing.Generator[ops.testing.Harness, None, None]:
    """Create ops.testing.Harness object and patch necessary functions in code."""
    mock_config = ""

    def read_config():
        return mock_config

    def write_config(config: str):
        nonlocal mock_config
        mock_config = config

    with (
        patch("chrony.Chrony.install"),
        patch("chrony.Chrony.restart"),
        patch("chrony.Chrony.write_config") as mock_write_config,
        patch("chrony.Chrony.read_config") as mock_read_config,
    ):
        mock_read_config.side_effect = read_config
        mock_write_config.side_effect = write_config
        yield ops.testing.Harness(ChronyCharm)
