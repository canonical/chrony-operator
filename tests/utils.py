# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test utils."""

import datetime
import textwrap
import typing

import cryptography.hazmat.primitives.asymmetric.ec
import cryptography.hazmat.primitives.asymmetric.ed25519
import cryptography.hazmat.primitives.serialization
import cryptography.x509

__all__ = [
    "TEST_CA_KEY",
    "TEST_CA_CERT",
    "TEST_KEY_PEM",
    "TEST_CERT_PEM",
    "TEST_CERT",
    "sign_csr",
    "get_csr_common_name",
]


TEST_CA_KEY = typing.cast(
    cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PrivateKey,
    cryptography.hazmat.primitives.serialization.load_pem_private_key(
        textwrap.dedent(
            """\
            -----BEGIN PRIVATE KEY-----
            MC4CAQAwBQYDK2VwBCIEIKXRPSEH+PyE0vCWNreeEB9AawKUMxrnMbrE2VlSdS/J
            -----END PRIVATE KEY-----
            """
        ).encode("ascii"),
        password=None,
    ),
)

TEST_CA_CERT = cryptography.x509.load_pem_x509_certificate(
    textwrap.dedent(
        """\
        -----BEGIN CERTIFICATE-----
        MIH0MIGnoAMCAQICFAJ4DT4qgqT9//Ib3U16e3jr2NphMAUGAytlcDAPMQ0wCwYD
        VQQDDAR0ZXN0MCAXDTUwMDEwMTAwMDAwMFoYDzIxMDAwMTAxMDAwMDAwWjAPMQ0w
        CwYDVQQDDAR0ZXN0MCowBQYDK2VwAyEAI6JWNp+aLp3U5M+kyrz6bEZJmEkzbNIB
        JUznVGbzyp2jEzARMA8GA1UdEwEB/wQFMAMBAf8wBQYDK2VwA0EA2rxwkt+ly/eU
        lxXlvlqWHz3cwn74Fs017JeabLU4NBhQdMmnbDRSQPI+eY37C+wAIShhpuNj2G1A
        ijZJx4d3AQ==
        -----END CERTIFICATE-----
        """
    ).encode("ascii")
)

TEST_KEY_PEM = """\
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIDJNJc0Waah56SZGaix4ohuGNq3JWAnELeDmTHtAVhu1oAoGCCqGSM49
AwEHoUQDQgAEhc7Ms3dFl+0B2V8lzj+d3ccRFIJtczHdyl2zvdmaGxPDwaeuCFtN
Q6mrp9tCDC2Xgvnz2RsFgkoBe2DJJJ314Q==
-----END EC PRIVATE KEY-----
"""

TEST_CERT_PEM = """\
-----BEGIN CERTIFICATE-----
MIIBVzCB/qADAgECAhQabfYp6Vrx1Ettn6UT8ZoqdDoQMDAKBggqhkjOPQQDAjAW
MRQwEgYDVQQDDAtleGFtcGxlLm9yZzAgFw01MDAxMDEwMDAwMDBaGA80MDAwMDEw
MTAwMDAwMFowFjEUMBIGA1UEAwwLZXhhbXBsZS5vcmcwWTATBgcqhkjOPQIBBggq
hkjOPQMBBwNCAASFzsyzd0WX7QHZXyXOP53dxxEUgm1zMd3KXbO92ZobE8PBp64I
W01Dqaun20IMLZeC+fPZGwWCSgF7YMkknfXhoygwJjAWBgNVHREEDzANggtleGFt
cGxlLm9yZzAMBgNVHRMBAf8EAjAAMAoGCCqGSM49BAMCA0gAMEUCIQCLomaxeDCK
1W9UruA7oRnq5XwxyZ6ylVyMOVysMFHeOAIgB80Jm/PGnN1+1ezINYe0ze5m1lZw
2dqWnx4GgL0LHe4=
-----END CERTIFICATE-----
"""

TEST_CERT = cryptography.x509.load_pem_x509_certificate(TEST_CERT_PEM.encode("ascii"))


def sign_csr(csr: bytes | str) -> str:
    """Sign a CSR with the TEST_CA_CERT."""
    if isinstance(csr, str):
        csr = csr.encode("ascii")
    csr_obj = cryptography.x509.load_pem_x509_csr(csr)
    cert = (
        cryptography.x509.CertificateBuilder()
        .subject_name(csr_obj.subject)
        .issuer_name(TEST_CA_CERT.subject)
        .public_key(csr_obj.public_key())
        .serial_number(cryptography.x509.random_serial_number())
        .not_valid_before(datetime.datetime(1950, 1, 1, tzinfo=datetime.timezone.utc))
        .not_valid_after(datetime.datetime(2100, 1, 1, tzinfo=datetime.timezone.utc))
        .add_extension(
            cryptography.x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(TEST_CA_KEY, algorithm=None)
    )
    return cert.public_bytes(cryptography.hazmat.primitives.serialization.Encoding.PEM).decode(
        "ascii"
    )


def get_csr_common_name(csr_pem: str) -> str:
    """Get the subject common name of a CSR."""
    csr = cryptography.x509.load_pem_x509_csr(csr_pem.encode("ascii"))
    subject = csr.subject
    common_name = subject.get_attributes_for_oid(cryptography.x509.NameOID.COMMON_NAME)[0].value
    return common_name if isinstance(common_name, str) else common_name.decode("ascii")
