# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Chrony controller."""

import logging
import pathlib
import textwrap
import typing
import urllib.parse

import pydantic
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd

logger = logging.getLogger(__name__)


class _PoolOptions(pydantic.BaseModel):
    """Chrony pool directive options.

    For more detail: https://chrony-project.org/doc/4.5/chrony.conf.html
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    minpoll: int | None = None
    maxpoll: int | None = None
    iburst: bool = False
    burst: bool = False
    key: str | None = None
    nts: bool = False
    certset: str | None = None
    maxdelay: float | None = None
    maxdelayratio: float | None = None
    maxdelaydevratio: float | None = None
    maxdelayquant: float | None = None
    mindelay: float | None = None
    asymmetry: float | None = None
    offset: float | None = None
    minsamples: int | None = None
    maxsamples: int | None = None
    filter: int | None = None
    offline: bool = False
    auto_offline: bool = False
    prefer: bool = False
    noselect: bool = False
    trust: bool = False
    require: bool = False
    xleave: bool = False
    polltarget: int | None = None
    presend: int | None = None
    minstratum: int | None = None
    version: int | None = None
    extfield: str | None = None
    maxsources: int | None = None

    def render_options(self) -> str:
        """Render pool options as chrony option string.

        Returns:
            Chrony pool directive option string.
        """
        options = []
        for field in sorted(f for f in _PoolOptions.model_fields if f != "copy"):
            value = getattr(self, field)
            if value is True:
                options.append(field)
            elif value is None or value is False:
                continue
            else:
                options.extend([field, str(value)])
        return " ".join(options)


class _NtpSource(_PoolOptions):
    """A NTP time source."""

    host: typing.Annotated[str, pydantic.StringConstraints(min_length=1)]
    port: int | None = None

    @classmethod
    def from_source_url(cls, url: str) -> "_NtpSource":
        """Parse a NTP time source from a URL.

        Args:
            url: URL to parse.

        Returns:
            Parsed NTP time source.

        Raises:
            ValueError: If the URL is invalid.
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ntp":
            raise ValueError(f"Invalid NTP source URL: {url}")
        query = dict(urllib.parse.parse_qsl(parsed.query))
        return cls(host=parsed.hostname, port=parsed.port, **query)  # type: ignore

    def render(self) -> str:
        """Render NTP time source as a chrony pool directive string.

        Returns:
            Chrony pool directive string.
        """
        directive = f"pool {self.host}"
        if self.port is not None and self.port != 123:
            directive += f" port {self.port}"
        options = self.render_options()
        if options:
            directive += f" {options}"
        return directive


class _NtsSource(_PoolOptions):
    """A NTP time source with NTS enabled."""

    host: typing.Annotated[str, pydantic.StringConstraints(min_length=1)]
    ntsport: int | None = None

    @classmethod
    def from_source_url(cls, url: str) -> "_NtsSource":
        """Parse a NTP time source with NTS enabled from a URL.

        Args:
            url: URL to parse.

        Returns:
            Parsed NTP time source.

        Raises:
            ValueError: If the URL is invalid.
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "nts":
            raise ValueError(f"Invalid NTS source URL: {url}")
        query = dict(urllib.parse.parse_qsl(parsed.query))
        return cls(host=parsed.hostname, ntsport=parsed.port, **query)  # type: ignore

    def render(self) -> str:
        """Render NTP time source as a chrony pool directive string with NTS enabled.

        Returns:
            Chrony pool directive string.
        """
        directive = f"pool {self.host} nts"
        if self.ntsport is not None and self.ntsport != 4460:
            directive += f" ntsport {self.ntsport}"
        options = self.render_options()
        if options:
            directive += f" {options}"
        return directive


TimeSource = _NtpSource | _NtsSource


class _ChronyConfig:
    """Chrony configuration file control."""

    def __init__(self, chrony: "Chrony", sources: list[TimeSource]) -> None:
        """Initialize chrony configuration object.

        Args:
            chrony: Chrony controller.
            sources: List of chrony time sources.
        """
        self._chrony = chrony
        self._sources = sources

    def render(self) -> str:
        """Generate the chrony configuration file content.

        Returns:
            Generated chrony configuration file content.
        """
        sources = "\n".join(s.render() for s in self._sources)
        return sources + textwrap.dedent(
            """
            bindcmdaddress 127.0.0.1
            driftfile /var/lib/chrony/chrony.drift
            ntsdumpdir /var/lib/chrony
            logdir /var/log/chrony
            maxupdateskew 100.0
            rtcsync
            makestep 1 3
            leapsectz right/UTC
            allow 0.0.0.0/0
            allow ::/0
            """
        )

    def apply(self) -> None:
        """Apply the new chrony configuration.

        This function compares the current chrony configuration with a new configuration. If they
        are the same, no changes are made. If they differ, the function updates the chrony
        configuration file with the new settings and restarts the chrony service.
        """
        current_config = self._chrony.read_config()
        new_config = self.render()
        if new_config != current_config:
            logger.info("Chrony config changed, apply and restart chrony")
            self._chrony.write_config(new_config)
            self._chrony.restart()


class Chrony:
    """Chrony service manager."""

    CONFIG_FILE = pathlib.Path("/etc/chrony/chrony.conf")

    @staticmethod
    def install() -> None:
        """Install the Chrony on the system."""
        apt.add_package(["chrony", "ca-certificates"], update_cache=True)  # pragma: nocover

    def read_config(self) -> str:
        """Read the current chrony configuration file.

        Returns:
            The current chrony configuration file content.
        """
        return self.CONFIG_FILE.read_text(encoding="utf-8")  # pragma: nocover

    def write_config(self, config: str) -> None:
        """Write the chrony configuration file.

        Args:
            config: The new chrony configuration file content.
        """
        self.CONFIG_FILE.write_text(config, encoding="utf-8")  # pragma: nocover

    @staticmethod
    def restart() -> None:
        """Restart the chrony service."""
        systemd.service_restart("chrony")  # pragma: nocover

    @staticmethod
    def parse_source_url(url: str) -> TimeSource:
        """Parse a time source from a URL.

        Args:
            url: URL to parse.

        Returns:
            Parsed TimeSource instance.

        Raises:
            ValueError: If the URL is invalid.
        """
        if url.startswith("ntp://"):
            return _NtpSource.from_source_url(url)
        if url.startswith("nts://"):
            return _NtsSource.from_source_url(url)
        raise ValueError(f"Invalid time source URL: {url}")

    def new_config(self, *, sources: list[TimeSource]) -> _ChronyConfig:
        """Create a new chrony configuration object.

        Args:
            sources: A list of time sources to be used by chrony.

        Returns:
            Chrony configuration object.

        Raises:
            ValueError: If the URL is invalid.
        """
        if not sources:
            raise ValueError("No time sources provided")
        return _ChronyConfig(chrony=self, sources=sources)
