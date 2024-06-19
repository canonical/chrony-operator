#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://juju.is/docs/sdk

"""Chrony charm."""

import logging
import typing

import ops

from chrony import Chrony, TimeSource

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
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

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
        self.unit.status = ops.WaitingStatus("waiting for configuration")

    def _on_config_changed(self, _: ops.EventBase) -> None:
        """Handle the "config-changed" event."""
        sources = self._get_time_sources()
        if not sources:
            self.unit.status = ops.BlockedStatus("no time source configured")
            return
        self.chrony.new_config(sources=sources).apply()
        self.unit.status = ops.ActiveStatus()

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
