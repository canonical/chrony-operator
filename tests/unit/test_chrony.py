# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=duplicate-code,missing-function-docstring

"""Chrony unit tests."""

import textwrap

import pytest

from src.chrony import Chrony

TIME_SOURCE_URL_EXAMPLES = [
    ["ntp://example.com", "pool example.com"],
    ["ntp://example.com:1234", "pool example.com port 1234"],
    ["ntp://example.com?iburst=true", "pool example.com iburst"],
    ["ntp://example.com?iburst=True", "pool example.com iburst"],
    ["ntp://example.com?iburst=TRUE", "pool example.com iburst"],
    ["ntp://example.com?iburst=1", "pool example.com iburst"],
    ["ntp://example.com?iburst=false", "pool example.com"],
    ["ntp://example.com?iburst=False", "pool example.com"],
    ["ntp://example.com?iburst=FALSE", "pool example.com"],
    ["ntp://example.com?iburst=0", "pool example.com"],
    [
        "ntp://example.com:1234?iburst=true&minpoll=10&polltarget=50",
        "pool example.com port 1234 iburst minpoll 10 polltarget 50",
    ],
    ["nts://example.com?require=true&offset=-0.1", "pool example.com nts offset -0.1 require"],
    ["nts://example.com:4461?require=true", "pool example.com nts ntsport 4461 require"],
]


@pytest.mark.parametrize("url,directive", TIME_SOURCE_URL_EXAMPLES)
def test_parse_source_url(url: str, directive: str):
    """
    arrange: receive a list of URL and directory pairs for testing.
    act: parse the source URL to get a configuration directive.
    assert: confirm that the rendered directory matches the expected directive.
    """
    assert Chrony.parse_source_url(url).render() == directive


INVALID_TIME_SOURCE_URL_EXAMPLES = [
    pytest.param("https://example.com", id="invalid protocol"),
    pytest.param("ntp://", id="no host"),
    pytest.param("ntp://example.com?offset=test", id="incorrect option type"),
    pytest.param("ntp://example.com?foobar=123", id="unknown options"),
]


@pytest.mark.parametrize("url", INVALID_TIME_SOURCE_URL_EXAMPLES)
def test_parse_invalid_source_url(url: str):
    """
    arrange: provide a list of invalid URL examples for parsing.
    act: attempt to parse the source URL which should be invalid.
    assert: expect a ValueError to be raised due to invalid URL format.
    """
    with pytest.raises(ValueError):
        Chrony.parse_source_url(url)


def test_render_chrony_config():
    """
    arrange: initialize Chrony object and parse time source URLs.
    act: generate a new configuration from parsed URLs.
    assert: verify that the rendered configuration matches the expected output.
    """
    chrony = Chrony()
    sources = [chrony.parse_source_url(s) for s in ["ntp://example.com", "nts://nts.example.com"]]
    assert chrony.new_config(sources=sources).render() == textwrap.dedent(
        """\
        pool example.com
        pool nts.example.com nts
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
