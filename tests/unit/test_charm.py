# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=duplicate-code,missing-function-docstring

"""Charm unit tests."""

import ops.testing


def test_config_time_sources(harness: ops.testing.Harness):
    harness.set_leader()
    harness.begin_with_initial_hooks()
    assert harness.charm.unit.status.name == "blocked"
    harness.charm.chrony.install.assert_called()

    harness.update_config({"sources": "ntp://example.com"})
    assert harness.charm.unit.status.name == "active"
    harness.charm.chrony.restart.assert_called()
    assert "pool example.com" in harness.charm.chrony.read_config()


def test_reconfig_time_sources(harness: ops.testing.Harness):
    harness.begin_with_initial_hooks()
    harness.update_config({"sources": "ntp://example.com"})
    assert "pool example.com" in harness.charm.chrony.read_config()
    assert harness.charm.chrony.restart.call_count == 1

    harness.update_config({"sources": "ntp://example.net"})
    assert "pool example.com" not in harness.charm.chrony.read_config()
    assert "pool example.net" in harness.charm.chrony.read_config()
    assert harness.charm.chrony.restart.call_count == 2


def test_same_time_sources(harness: ops.testing.Harness):
    harness.begin_with_initial_hooks()
    harness.update_config({"sources": "ntp://example.com"})
    assert harness.charm.chrony.restart.call_count == 1

    harness.update_config({"sources": "ntp://example.com,"})
    assert harness.charm.chrony.restart.call_count == 1
