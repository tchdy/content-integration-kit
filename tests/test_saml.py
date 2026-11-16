"""End-to-end SAML tests: a fake IdP signs real SAML Responses with its own
key, and we post them to the ACS exactly as a browser would."""

import base64
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from lxml import etree
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.utils import OneLogin_Saml2_Utils

from .conftest import FIXTURES, IDP_CERT, IDP_ENTITY_ID, IDP_KEY

SP_ENTITY = "https://kit.test/saml/metadata"
ACS = "https://kit.test/saml/acs"


def _ts(delta_minutes: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(minutes=delta_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_response(*, audience=SP_ENTITY, destination=ACS, not_on_or_after=5, in_response_to=None,
                  email="ada@example.com", key=IDP_KEY, cert=IDP_CERT, sign=True) -> str:
    irt = f' InResponseTo="{in_response_to}"' if in_response_to else ""
    assertion = f"""<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_ts()}">
<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>
<saml:Subject>
  <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{email}</saml:NameID>
  <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
    <saml:SubjectConfirmationData NotOnOrAfter="{_ts(not_on_or_after)}" Recipient="{destination}"{irt}/>
  </saml:SubjectConfirmation>
</saml:Subject>
<saml:Conditions NotBefore="{_ts(-5)}" NotOnOrAfter="{_ts(not_on_or_after)}">
  <saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>
</saml:Conditions>
<saml:AuthnStatement AuthnInstant="{_ts()}" SessionIndex="_session1">
  <saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef></saml:AuthnContext>
</saml:AuthnStatement>
<saml:AttributeStatement>
  <saml:Attribute Name="firstName"><saml:AttributeValue>Ada</saml:AttributeValue></saml:Attribute>
  <saml:Attribute Name="groups"><saml:AttributeValue>editors</saml:AttributeValue></saml:Attribute>
</saml:AttributeStatement>
</saml:Assertion>"""
    if sign:
        assertion = OneLogin_Saml2_Utils.add_sign(assertion, key, cert, sign_algorithm=C.RSA_SHA256,
                                                  digest_algorithm=C.SHA256)
        assertion = assertion.decode() if isinstance(assertion, bytes) else assertion
        assertion = assertion.split("?>", 1)[-1]  # drop XML declaration before embedding
    response = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_ts()}" Destination="{destination}"{irt}>
<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>
<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
{assertion}
</samlp:Response>"""
    return base64.b64encode(response.encode()).decode()


def other_keypair():
    key, crt = FIXTURES / "rogue.key", FIXTURES / "rogue.crt"
    if not key.exists():
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=rogue", "-keyout", str(key), "-out", str(crt)], check=True, capture_output=True)
    return key.read_text(), crt.read_text()


def test_sp_metadata_is_valid_and_lists_acs(client):
    r = client.get("/saml/metadata")
    assert r.status_code == 200
    root = etree.fromstring(r.content)
    assert root.get("entityID") == SP_ENTITY
    acs = root.find(".//{urn:oasis:names:tc:SAML:2.0:metadata}AssertionConsumerService")
    assert acs.get("Location") == ACS


def test_sp_metadata_works_even_if_idp_is_unreachable(client, monkeypatch):
    from app import saml_sp
    saml_sp._idp_settings.cache_clear()
    monkeypatch.setenv("IDP_METADATA_FILE", "/nonexistent.xml")
    assert client.get("/saml/metadata").status_code == 200
    r = client.get("/saml/login", follow_redirects=False)
    assert r.status_code == 503 and "IdP metadata" in r.json()["detail"]
    saml_sp._idp_settings.cache_clear()


def test_login_redirects_to_idp_with_authn_request(client):
    r = client.get("/saml/login", follow_redirects=False)
    assert r.status_code == 302
    url = urlparse(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://idp.test/sso"
    assert "SAMLRequest" in parse_qs(url.query)


def test_full_sp_initiated_login(client):
    # Start login so the session holds the AuthnRequest id, then answer it.
    r = client.get("/saml/login?next=/articles", follow_redirects=False)
    saml_request = parse_qs(urlparse(r.headers["location"]).query)["SAMLRequest"][0]
    xml = OneLogin_Saml2_Utils.decode_base64_and_inflate(saml_request)
    request_id = etree.fromstring(xml if isinstance(xml, bytes) else xml.encode()).get("ID")

    r = client.post("/saml/acs", data={"SAMLResponse": make_response(in_response_to=request_id),
                                       "RelayState": "/articles"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/articles"
    me = client.get("/me").json()
    assert me["name_id"] == "ada@example.com"
    assert me["attributes"]["groups"] == ["editors"]


def test_open_redirect_in_relay_state_is_blocked(client):
    r = client.post("/saml/acs", data={"SAMLResponse": make_response(), "RelayState": "https://evil.test"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/me"


@pytest.mark.parametrize("kwargs,expected", [
    ({"audience": "https://someone-else.test"}, "audience"),
    ({"not_on_or_after": -1}, "subjectconfirmation"),  # expired bearer confirmation
    ({"destination": "https://kit.test/wrong"}, "was received at"),
    ({"sign": False}, "signature"),
])
def test_bad_responses_are_rejected(client, kwargs, expected):
    r = client.post("/saml/acs", data={"SAMLResponse": make_response(**kwargs)})
    assert r.status_code == 401
    assert expected in r.text.lower()


def test_response_signed_by_unknown_key_is_rejected(client):
    key, cert = other_keypair()
    r = client.post("/saml/acs", data={"SAMLResponse": make_response(key=key, cert=cert)})
    assert r.status_code == 401


def test_tampered_assertion_is_rejected(client):
    raw = base64.b64decode(make_response()).decode().replace("ada@example.com", "admin@example.com")
    r = client.post("/saml/acs", data={"SAMLResponse": base64.b64encode(raw.encode()).decode()})
    assert r.status_code == 401
