# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Other test utils."""

import json
import typing

import cryptography.hazmat.primitives.asymmetric.ed25519
import cryptography.hazmat.primitives.serialization
import cryptography.x509
import ops.testing

from tests.utils import TEST_CA_CERT, TEST_CA_KEY, get_csr_common_name, sign_csr

__all__ = ["TEST_CA_KEY", "TEST_CA_CERT", "sign_csr", "get_csr_common_name", "TlsProvider"]


class TlsProvider:
    """tls-certificates provider."""

    def __init__(self, harness: ops.testing.Harness, remote_app="tls-provider"):
        """Initialize TlsProvider."""
        self.harness = harness
        self.relation_id: int | None = None
        self.provider_app = remote_app
        self.signed: dict[str, str] = {}

    def relate(self):
        """Create the tls-certificates relation."""
        self.relation_id = self.harness.add_relation("nts-certificates", self.provider_app)

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
            ca_cert = (
                TEST_CA_CERT.public_bytes(
                    cryptography.hazmat.primitives.serialization.Encoding.PEM
                )
                .decode("ascii")
                .strip()
            )
            cert = sign_csr(csr).strip()
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
