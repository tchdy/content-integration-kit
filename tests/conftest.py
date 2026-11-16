"""Shared fixtures. Env vars are set before the app is imported, so every test
runs against a throwaway database and a local test IdP (no network)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _make_idp_keypair() -> tuple[str, str]:
    """Self-signed certificate for the fake IdP, generated once per run."""
    FIXTURES.mkdir(exist_ok=True)
    key, crt = FIXTURES / "idp.key", FIXTURES / "idp.crt"
    if not key.exists():
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
             "-subj", "/CN=test-idp", "-keyout", str(key), "-out", str(crt)],
            check=True, capture_output=True,
        )
    return key.read_text(), crt.read_text()


IDP_ENTITY_ID = "https://idp.test/entity"
IDP_SSO_URL = "https://idp.test/sso"
IDP_KEY, IDP_CERT = _make_idp_keypair()
_cert_body = "".join(line for line in IDP_CERT.splitlines() if "CERTIFICATE" not in line)

(FIXTURES / "idp_metadata.xml").write_text(f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{IDP_ENTITY_ID}">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><ds:X509Data><ds:X509Certificate>{_cert_body}</ds:X509Certificate></ds:X509Data></ds:KeyInfo>
    </md:KeyDescriptor>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="{IDP_SSO_URL}"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>
""")

os.environ.update({
    "BASE_URL": "https://kit.test",
    "WEBHOOK_SECRET": "test-secret",
    "SESSION_SECRET": "test-session",
    "IDP_METADATA_FILE": str(FIXTURES / "idp_metadata.xml"),
})


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path / "kit.db"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app, base_url="https://kit.test")
