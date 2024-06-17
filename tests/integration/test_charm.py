# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests."""

import logging
import socket

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(chrony_app, ops_test):
    """Test building and deploying the chrony charm."""
    await chrony_app.set_config({"sources": "ntp://ntp.ubuntu.com"})
    await ops_test.model.wait_for_idle(status="active")


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("chrony_app")
async def test_ntp_server(get_unit_ips):
    """Test the functionality of the chrony charm as a NTP server."""
    unit_ips = await get_unit_ips()
    for unit_ip in unit_ips:
        # construct a simple NTPv4 request
        ntp_request = b"\x23" + b"\x00" * 47
        ntp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ntp_sock.sendto(ntp_request, (unit_ip, 123))
        assert ntp_sock.recvfrom(65535)[0]
