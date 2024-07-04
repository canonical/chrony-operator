# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit test utils."""

import datetime
import json
import textwrap
import typing

import cryptography.hazmat.primitives.asymmetric.ed25519
import cryptography.hazmat.primitives.serialization
import cryptography.x509
import ops.testing

__all__ = ["TEST_CA_KEY", "TEST_CA_CERT", "sign_csr", "get_csr_common_name"]


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


class TlsProvider:
    """tls-certificates provider."""

    def __init__(self, harness: ops.testing.Harness, remote_app="tls-provider"):
        self.harness = harness
        self.relation_id: int | None = None
        self.provider_app = remote_app
        self.signed: dict[str, str] = {}

    def relate(self):
        """Create the tls-certificates relation."""
        self.relation_id = self.harness.add_relation("certificates", self.provider_app)

    def unrelate(self):
        """Break the tls-certificates relation."""
        self.harness.remove_relation(typing.cast(int, self.relation_id))

    def sign(self):
        """Sign required CSRs from the requirer."""
        certificate_signing_requests = json.loads(
            self.harness.get_relation_data(
                typing.cast(int, self.relation_id), self.harness.charm.unit.name
            )["certificate_signing_requests"]
        )
        certificates = json.loads(
            self.harness.get_relation_data(
                typing.cast(int, self.relation_id), self.provider_app
            ).get("certificates", "[]")
        )
        certificates = [
            cert
            for cert in certificates
            if cert["certificate_signing_request"]
            not in [csr["certificate_signing_request"] for csr in certificate_signing_requests]
        ]
        fulfilled_csr = [cert["certificate_signing_request"] for cert in certificates]
        for csr in certificate_signing_requests:
            csr = csr["certificate_signing_request"]
            if csr in fulfilled_csr:
                continue
            ca_cert = TEST_CA_CERT.public_bytes(
                cryptography.hazmat.primitives.serialization.Encoding.PEM
            ).decode("ascii")
            cert = sign_csr(csr)
            self.signed[csr.strip()] = cert
            certificates.append(
                {
                    "ca": ca_cert,
                    "chain": [cert, ca_cert],
                    "certificate_signing_request": csr,
                    "certificate": cert,
                }
            )
        self.harness.update_relation_data(
            typing.cast(int, self.relation_id),
            self.provider_app,
            {
                "certificates": json.dumps(certificates),
            },
        )

    def revoke(self):
        """Revoke all certificates currently signed."""
        certificates = json.loads(
            self.harness.get_relation_data(
                typing.cast(int, self.relation_id), self.provider_app
            ).get("certificates", "[]")
        )
        for cert in certificates:
            cert["revoked"] = True
        self.harness.update_relation_data(
            typing.cast(int, self.relation_id),
            self.provider_app,
            {
                "certificates": json.dumps(certificates),
            },
        )

    def get_signed(self, csr: str) -> str:
        """Get the signed certificate for the given CSR from signing history."""
        return self.signed[csr.strip()]