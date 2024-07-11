# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=duplicate-code,missing-function-docstring

"""Other charm tests."""

# pylint: disable=protected-access

import hashlib
import pathlib

import ops.testing

from tests.other.utils import TlsProviderStub, get_csr_common_name


def test_tls_keychain_initiation(harness: ops.testing.Harness):
    """
    arrange: initialize the testing harness and run initial hooks.
    act: retrieve the private key from the TLS keychain of the charm.
    assert: verify that a private key is available in the TLS keychain.
    """
    harness.begin_with_initial_hooks()
    assert harness.charm.tls_keychain.get_private_key()


def test_certificates_integration_after_server_name(harness: ops.testing.Harness):
    """
    arrange: start the harness with initial hooks and update the server name configuration.
    act: relate the charm with a TLS certificate provider.
    assert: the charm request the TLS certificate correctly.
    """
    harness.begin_with_initial_hooks()
    harness.update_config({"server-name": "example.com"})
    assert not harness.charm.tls_keychain.get_csr()
    assert not harness.charm.tls_keychain.get_server_name()

    harness.add_relation("nts-certificates", "tls-certificate-provider")
    assert get_csr_common_name(harness.charm.tls_keychain.get_csr()) == "example.com"
    assert harness.charm.tls_keychain.get_server_name() == "example.com"


def test_server_name_after_certificates_integration(harness: ops.testing.Harness):
    """
    arrange: initialize the harness, and establish a relation with the TLS certificate provider.
    act: update the server name configuration.
    assert: the charm request the TLS certificate correctly.
    """
    harness.begin_with_initial_hooks()
    harness.add_relation("nts-certificates", "tls-certificate-provider")
    assert not harness.charm.tls_keychain.get_csr()
    assert not harness.charm.tls_keychain.get_server_name()

    harness.update_config({"server-name": "example.com"})
    assert get_csr_common_name(harness.charm.tls_keychain.get_csr()) == "example.com"
    assert harness.charm.tls_keychain.get_server_name() == "example.com"


def test_alter_server_name(harness: ops.testing.Harness):
    """
    arrange: initialize the harness, and set up the relation with the TLS certificate provider.
    act: change the server name in the configuration to a different value.
    assert: the charm request a new TLS certificate with the new server name correctly.
    """
    harness.update_config({"server-name": "example.com"})
    harness.begin_with_initial_hooks()
    harness.add_relation("nts-certificates", "tls-certificate-provider")
    assert get_csr_common_name(harness.charm.tls_keychain.get_csr()) == "example.com"
    assert harness.charm.tls_keychain.get_server_name() == "example.com"

    harness.update_config({"server-name": "example.net"})
    assert get_csr_common_name(harness.charm.tls_keychain.get_csr()) == "example.net"
    assert harness.charm.tls_keychain.get_server_name() == "example.net"


def test_setup_nts(harness: ops.testing.Harness):
    """
    arrange: configure the server and source setting, and set up the TLS provider.
    act: none.
    assert: ensure that the certificates are correctly placed and configured within the NTS setup.
    """
    harness.update_config({"server-name": "example.com", "sources": "ntp://example.com"})
    harness.begin_with_initial_hooks()
    tls_provider = TlsProviderStub(harness)
    tls_provider.relate()
    tls_provider.sign()

    assert harness.charm.tls_keychain.get_key_pairs()
    assert "ntsservercert /etc/chrony/certs/0000.crt" in harness.charm.chrony.read_config()
    assert "ntsserverkey /etc/chrony/certs/0000.key" in harness.charm.chrony.read_config()
    csr = harness.charm.tls_keychain.get_csr()
    chain_on_disk = harness.charm.chrony._read_certs_file(
        pathlib.Path("/etc/chrony/certs/0000.crt")
    )
    assert tls_provider.get_signed(csr) in chain_on_disk


def test_tls_certificate_revoked(harness: ops.testing.Harness):
    """
    arrange: set up the server name and sources in the configuration, and set up the TLS provider.
    act: revoke and re-sign the TLS certificate.
    assert: confirm that the certificate changes to the latest one after revocation and re-signing.
    """
    harness.update_config({"server-name": "example.com", "sources": "ntp://example.com"})
    harness.begin_with_initial_hooks()
    tls_provider = TlsProviderStub(harness)
    tls_provider.relate()
    tls_provider.sign()
    chain_on_disk = harness.charm.chrony._read_certs_file(
        pathlib.Path("/etc/chrony/certs/0000.crt")
    )
    tls_provider.revoke()
    assert chain_on_disk == harness.charm.chrony._read_certs_file(
        pathlib.Path("/etc/chrony/certs/0000.crt")
    )
    tls_provider.sign()
    new_chain = harness.charm.chrony._read_certs_file(pathlib.Path("/etc/chrony/certs/0000.crt"))
    assert new_chain != chain_on_disk
    assert len(tls_provider.signed) == 2
    assert list(tls_provider.signed.values())[-1] in new_chain
    assert len(harness.charm.tls_keychain.get_key_pairs()) == 1


def test_tls_certificate_expired(harness: ops.testing.Harness):
    """
    arrange: set up the server name and sources in the configuration, and set up the TLS provider.
    act: expire and re-sign the TLS certificate.
    assert: confirm that the certificate changes to the latest one after revocation and re-signing.
    """
    harness.update_config({"server-name": "example.com", "sources": "ntp://example.com"})
    harness.begin_with_initial_hooks()
    tls_provider = TlsProviderStub(harness)
    tls_provider.relate()
    tls_provider.sign()
    assert len(tls_provider.signed) == 1
    csr = harness.charm.tls_keychain.get_csr()
    csr_sha256 = hashlib.sha256(csr.strip().encode()).hexdigest()
    secret_label = f"afd8c2bccf834997afce12c2706d2ede-{csr_sha256}"
    secret_info = harness.charm.model.get_secret(label=secret_label).get_info()
    harness.trigger_secret_expiration(secret_info.id, secret_info.revision)

    assert csr != harness.charm.tls_keychain.get_csr()
    tls_provider.sign()
    assert len(tls_provider.signed) == 2


def test_server_name_change(harness: ops.testing.Harness):
    """
    arrange: set up the server name and sources in the configuration, and set up the TLS provider.
    act: change the server name charm configuration.
    assert: confirm that the certificate changed accordingly.
    """
    harness.update_config({"server-name": "example.com", "sources": "ntp://example.com"})
    harness.begin_with_initial_hooks()
    tls_provider = TlsProviderStub(harness)
    tls_provider.relate()
    tls_provider.sign()

    harness.update_config({"server-name": "example.net", "sources": "ntp://example.com"})
    tls_provider.sign()

    assert len(tls_provider.signed) == 2
    assert get_csr_common_name(list(tls_provider.signed.keys())[0]) == "example.com"
    assert get_csr_common_name(list(tls_provider.signed.keys())[1]) == "example.net"
    assert list(tls_provider.signed.values())[-1] in harness.charm.chrony._read_certs_file(
        pathlib.Path("/etc/chrony/certs/0000.crt")
    )


def test_server_name_reset(harness: ops.testing.Harness):
    """
    arrange: set up the server name and sources in the configuration, and set up the TLS provider.
    act: unset the server name charm configuration.
    assert: confirm that certificates and NTS set up are teared down.
    """
    harness.update_config({"server-name": "example.com", "sources": "ntp://example.com"})
    harness.begin_with_initial_hooks()
    tls_provider = TlsProviderStub(harness)
    tls_provider.relate()
    tls_provider.sign()
    assert "ntsservercert" in harness.charm.chrony.read_config()
    assert "ntsserverkey" in harness.charm.chrony.read_config()
    assert len(tls_provider.signed) == 1
    assert len(harness.charm.tls_keychain.get_key_pairs()) == 1

    harness.update_config({}, unset=["server-name"])

    assert "ntsservercert" not in harness.charm.chrony.read_config()
    assert "ntsserverkey" not in harness.charm.chrony.read_config()
    assert len(tls_provider.signed) == 1
    assert len(harness.charm.tls_keychain.get_key_pairs()) == 0


def test_remove_tls_certificates_integration(harness: ops.testing.Harness):
    """
    arrange: set up the server name and sources in the configuration, and set up the TLS provider.
    act: remove the TLS provider integration.
    assert: confirm that certificates and NTS set up are teared down.
    """
    harness.update_config({"server-name": "example.com", "sources": "ntp://example.com"})
    harness.begin_with_initial_hooks()
    tls_provider = TlsProviderStub(harness)
    tls_provider.relate()
    tls_provider.sign()
    assert len(tls_provider.signed) == 1
    assert "ntsservercert" in harness.charm.chrony.read_config()
    assert "ntsserverkey" in harness.charm.chrony.read_config()
    assert len(harness.charm.tls_keychain.get_key_pairs()) == 1

    tls_provider.unrelate()

    assert len(tls_provider.signed) == 1
    assert "ntsservercert" not in harness.charm.chrony.read_config()
    assert "ntsserverkey" not in harness.charm.chrony.read_config()
    assert len(harness.charm.tls_keychain.get_key_pairs()) == 0
