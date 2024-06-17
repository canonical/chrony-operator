# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test fixtures."""

import json
import os.path

import juju.application
import pytest
import pytest_asyncio
from pytest_operator.plugin import OpsTest


@pytest_asyncio.fixture(scope="module")
async def chrony_app(
    ops_test: OpsTest, pytestconfig: pytest.Config
) -> juju.application.Application:
    """Build and deploy the charm in the testing model."""
    charm = pytestconfig.getoption("--charm-file")
    if not charm:
        charm = await ops_test.build_charm(".")
    assert ops_test.model
    charm = await ops_test.model.deploy(os.path.abspath(charm), series="jammy")
    await ops_test.model.wait_for_idle(timeout=900)
    return charm


@pytest_asyncio.fixture
async def get_unit_ips(ops_test: OpsTest):
    """A function to get unit ips of a charm application."""

    async def _get_unit_ips(name: str = "chrony"):
        _, status, _ = await ops_test.juju("status", "--format", "json")
        status = json.loads(status)
        units = status["applications"][name]["units"]
        ip_list = []
        for key in sorted(units.keys(), key=lambda n: int(n.split("/")[-1])):
            ip_list.append(units[key]["public-address"])
        return ip_list

    return _get_unit_ips
