#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://juju.is/docs/sdk

"""Chrony charm."""

import logging
import typing

import ops
from charms.tls_certificates_interface.v3 import tls_certificates

from chrony import Chrony, TimeSource
from keychain import TlsKeychain

logger = logging.getLogger(__name__)


class ChronyCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, *args: typing.Any):
        """Construct.

        Args:
            args: Arguments passed to the CharmBase parent constructor.
        """
        super().__init__(*args)
        self.chrony = Chrony()
        self.certificates = tls_certificates.TLSCertificatesRequiresV3(self, "certificates")
        self.tls_keychain = TlsKeychain(charm=self, namespace="certificates")
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(
            self.on.certificates_relation_created, self._on_certificates_relation_created
        )
        self.framework.observe(
            self.on.certificates_relation_broken, self._on_certificates_relation_broken
        )
        self.framework.observe(
            self.certificates.on.certificate_available, self._on_certificate_available
        )
        self.framework.observe(
            self.certificates.on.certificate_expiring, self._on_certificate_expiring
        )
        self.framework.observe(
            self.certificates.on.certificate_invalidated, self._on_certificate_invalidated
        )

    def _on_certificates_relation_created(self, _: ops.RelationCreatedEvent) -> None:
        """Handle the certificates relation-creation event."""
        if self.unit.is_leader():
            self.unit.open_port("tcp", 4460)
        self._do_renew_certificate()

    def _on_certificates_relation_broken(self, _: ops.RelationBrokenEvent) -> None:
        """Handle the certificates relation-broken event."""
        if self.unit.is_leader():
            self.unit.close_port("tcp", 4460)
        self.tls_keychain.clear()
        self._do_config()

    def _on_certificate_expiring(self, _: ops.EventBase) -> None:
        """Handle the certificates expiring event."""
        self._do_renew_certificate()

    def _on_certificate_invalidated(self, _: ops.EventBase) -> None:
        """Handle the certificates invalidated event."""
        self._do_renew_certificate()

    def _do_renew_certificate(self) -> None:
        """Handle the event when certificate is unavailable."""
        if not self._get_server_name():
            return
        self._renew_certificate()

    def _on_certificate_available(self, event: tls_certificates.CertificateAvailableEvent) -> None:
        """Handle the certificate-available event.

        Args:
            event: certificate-available event object.
        """
        self.tls_keychain.set_chain(event.chain_as_pem())
        self._do_config()

    def _renew_certificate(self) -> None:
        """Renew the certificate.

        Raises:
            RuntimeError: canary exception
        """
        old_csr = self.tls_keychain.get_csr()
        private_key = self.tls_keychain.get_private_key()
        if not self._get_server_name():
            # canary exception
            raise RuntimeError("no server name")  # pragma: nocover
        self.certificates.get_expiring_certificates()
        new_csr = tls_certificates.generate_csr(
            private_key=private_key.encode(),
            subject=self._get_server_name(),
            sans_dns=[self._get_server_name(), f"*.{self._get_server_name()}"],
        )
        if not old_csr:
            self.certificates.request_certificate_creation(certificate_signing_request=new_csr)
        else:
            self.certificates.request_certificate_renewal(
                old_certificate_signing_request=old_csr.encode(),
                new_certificate_signing_request=new_csr,
            )
        self.tls_keychain.set_server_name(self._get_server_name())
        self.tls_keychain.set_csr(new_csr.decode(encoding="ascii"))
        self.unit.status = ops.WaitingStatus("Waiting for new certificate")

    def _revoke_certificate(self) -> None:
        """Renew the certificate."""
        csr = self.tls_keychain.get_csr()
        if csr:
            self.certificates.request_certificate_revocation(csr.encode())
        self.tls_keychain.clear()

    def _on_install(self, _: ops.EventBase) -> None:
        """Handle install event."""
        self._do_install()

    def _on_upgrade_charm(self, _: ops.EventBase) -> None:
        """Handle upgrade-charm event."""
        self._do_install()

    def _do_install(self) -> None:
        """Install required packages and open NTP port."""
        self.unit.status = ops.MaintenanceStatus("installing chrony")
        self.chrony.install()
        self.unit.open_port("udp", 123)
        if not self.tls_keychain.get_private_key():
            self.tls_keychain.set_private_key(
                tls_certificates.generate_private_key().decode("ascii")
            )
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        """Handle the "config-changed" event."""
        if (
            self._get_server_name()
            and self.model.get_relation("certificates")
            and (
                not self.tls_keychain.get_key_pairs()
                or self.tls_keychain.get_server_name() != self._get_server_name()
            )
        ):
            self._do_config()
            self._renew_certificate()
            return
        if not self._get_server_name() and self.tls_keychain.get_private_key():
            self._revoke_certificate()
        self._do_config()

    def _do_config(self) -> None:
        """Configure chrony."""
        sources = self._get_time_sources()
        if not sources:
            self.unit.status = ops.BlockedStatus("no time source configured")
            return
        self.chrony.new_config(
            sources=sources, tls_key_pairs=self.tls_keychain.get_key_pairs()
        ).apply()
        self.unit.status = ops.ActiveStatus()

    def _get_server_name(self) -> str | None:
        """Get server name from charm configuration.

        Returns:
            The server name, None if not configured.
        """
        return typing.cast(str | None, self.config.get("server-name"))

    def _get_time_sources(self) -> list[TimeSource]:
        """Get time sources from charm configuration.

        Returns:
            Time source objects.
        """
        urls = typing.cast(str, self.config.get("sources"))
        return [
            self.chrony.parse_source_url(url.strip()) for url in urls.split(",") if url.strip()
        ]


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(ChronyCharm)
