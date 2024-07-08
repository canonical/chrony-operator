# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test utils."""

import socket
import ssl
import typing

import cryptography.x509

__all__ = ["get_tls_certificates", "get_sans"]


def get_tls_certificates(
    host, port=4460, server_name=None, verify=True, cadata=None
) -> cryptography.x509.Certificate:
    """Retrieve the TLS certificate from a specified TLS server."""
    context = ssl.create_default_context(cadata=cadata)
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    server_name = host if server_name is None else server_name
    with socket.create_connection((host, port)) as sock:
        with context.wrap_socket(sock, server_hostname=server_name) as ssock:
            cert = cryptography.x509.load_der_x509_certificate(
                typing.cast(bytes, ssock.getpeercert(binary_form=True))
            )
            return cert


def get_sans(certificate: cryptography.x509.Certificate) -> list[str]:
    """Extract the Subject Alternative Names (SANs) from a given X.509 certificate."""
    san_extension = certificate.extensions.get_extension_for_oid(
        cryptography.x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME
    )
    return san_extension.value.get_values_for_type(cryptography.x509.DNSName)  # type: ignore


def get_common_name(certificate: cryptography.x509.Certificate) -> str:
    """Extract the common name from a given X.509 certificate subject."""
    subject = certificate.subject
    common_name_oid = cryptography.x509.oid.NameOID.COMMON_NAME
    return subject.get_attributes_for_oid(common_name_oid)[0].value  # type: ignore
