# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests."""

import logging
import socket
import ssl

import pytest

from tests.integration.utils import get_sans, get_tls_certificates

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy(chrony_app, ops_test):
    """
    arrange: set up the chrony charm with a specific NTP source configuration.
    act: deploy the chrony charm and wait for it to reach the 'active' state.
    assert: ensure the application transitions to 'active' status after deployment.
    """
    await chrony_app.set_config({"sources": "ntp://ntp.ubuntu.com"})
    await ops_test.model.wait_for_idle(status="active")


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("chrony_app")
async def test_ntp_server(get_unit_ips):
    """
    arrange: set up the chrony charm with a specific NTP source configuration.
    act: send a simple NTPv4 request to each unit.
    assert: ensure each unit responds correctly to the NTP request.
    """
    unit_ips = await get_unit_ips()
    for unit_ip in unit_ips:
        ntp_request = b"\x23" + b"\x00" * 47  # construct a simple NTPv4 request
        ntp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ntp_sock.sendto(ntp_request, (unit_ip, 123))
        assert ntp_sock.recvfrom(65535)[0]


async def test_tls_certificates(chrony_app, self_signed_certificates_app, get_unit_ips, ops_test):
    """
    arrange: relate with self-signed-certificate application.
    act: update chrony charm config to use different server names.
    assert: confirm that the SANs in the retrieved certificates match configured server name.
    """
    action = await self_signed_certificates_app.units[0].run_action("get-ca-certificate")
    await action.wait()
    ca_cert = action.results["ca-certificate"]

    await chrony_app.set_config({"server-name": "example.com"})
    await ops_test.model.add_relation(chrony_app.name, self_signed_certificates_app.name)
    await ops_test.model.wait_for_idle(status="active")
    for unit_ip in await get_unit_ips():
        cert = get_tls_certificates(unit_ip, cadata=ca_cert, server_name="example.com")
        assert sorted(get_sans(cert)) == sorted(["example.com", "*.example.com"])

    await chrony_app.set_config({"server-name": "example.net"})
    await ops_test.model.wait_for_idle(status="active")
    for unit_ip in await get_unit_ips():
        cert = get_tls_certificates(unit_ip, cadata=ca_cert, server_name="example.net")
        assert sorted(get_sans(cert)) == sorted(["example.net", "*.example.net"])
        with pytest.raises(ssl.SSLCertVerificationError):
            get_tls_certificates(unit_ip, cadata=ca_cert, server_name="example.com")
