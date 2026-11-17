"""SAML 2.0 Service Provider (SP) built on python3-saml.

Flow (SP-initiated):
  1. /saml/login  -> redirect the browser to the IdP with an AuthnRequest.
  2. User signs in at the IdP.
  3. IdP POSTs a signed <Response> to /saml/acs (Assertion Consumer Service).
  4. We validate it: signature against the IdP certificate, Destination,
     Audience, time conditions (NotBefore / NotOnOrAfter), InResponseTo.
  5. On success, put NameID + attributes in the session.

The IdP is configured from its metadata (entity id, SSO URL, signing cert),
so switching from mocksaml.com to Okta / Entra ID is a config change only.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

import httpx
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from onelogin.saml2.settings import OneLogin_Saml2_Settings

from .config import Settings


class IdPConfigError(RuntimeError):
    """IdP metadata missing, unreachable, or lacking what the SP needs."""


# Sent when fetching IdP metadata. python3-saml's own fetch uses Python's default
# "Python-urllib" User-Agent, which bot protection on some IdPs (mocksaml.com) rejects with 403.
METADATA_USER_AGENT = "content-integration-kit/1.0 (SAML SP metadata fetch)"


def _fetch_metadata(url: str) -> str:
    resp = httpx.get(
        url,
        timeout=10,
        follow_redirects=True,
        headers={
            "User-Agent": METADATA_USER_AGENT,
            "Accept": "application/samlmetadata+xml, application/xml;q=0.9, text/xml;q=0.8",
        },
    )
    resp.raise_for_status()
    return resp.text


@lru_cache(maxsize=4)
def _idp_settings(metadata_url: str, metadata_file: str | None) -> dict:
    try:
        if metadata_file:
            with open(metadata_file, encoding="utf-8") as fh:
                parsed = OneLogin_Saml2_IdPMetadataParser.parse(fh.read())
        else:
            parsed = OneLogin_Saml2_IdPMetadataParser.parse(_fetch_metadata(metadata_url))
    except Exception as exc:  # network, TLS, malformed XML
        raise IdPConfigError(f"Could not load IdP metadata from {metadata_file or metadata_url}: {exc}") from exc
    idp = parsed.get("idp", {})
    if not idp.get("singleSignOnService", {}).get("url"):
        raise IdPConfigError("IdP metadata has no HTTP-Redirect SingleSignOnService")
    if not (idp.get("x509cert") or idp.get("x509certMulti")):
        raise IdPConfigError("IdP metadata has no signing certificate; responses could not be verified")
    return parsed


def build_settings(cfg: Settings, include_idp: bool = True) -> dict:
    idp = _idp_settings(cfg.idp_metadata_url, cfg.idp_metadata_file) if include_idp else {"idp": {}}
    return {
        "strict": True,  # never turn off outside local debugging: it disables most checks
        "debug": False,
        "sp": {
            "entityId": cfg.sp_entity_id,
            "assertionConsumerService": {
                "url": cfg.acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": idp["idp"],
        "security": {
            # Either the Response or the Assertion must be signed; python3-saml
            # rejects a response with no signature at all when strict=True.
            "wantAssertionsSigned": False,
            "wantMessagesSigned": False,
            "authnRequestsSigned": False,
            "rejectDeprecatedAlgorithm": True,
        },
    }


def sp_metadata(cfg: Settings) -> str:
    """SP metadata XML to give to the customer's IdP admin."""
    # SP metadata must be available even if the IdP is down: it's what you send
    # the customer's IdP admin before their side is configured.
    settings = OneLogin_Saml2_Settings(build_settings(cfg, include_idp=False), sp_validation_only=True)
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        raise ValueError(f"Invalid SP metadata: {errors}")
    return metadata.decode() if isinstance(metadata, bytes) else metadata


def request_data(cfg: Settings, path: str, get: dict, post: dict) -> dict:
    """python3-saml needs the URL the IdP posted to. Build it from BASE_URL,
    not the incoming request, because behind a proxy (Render, a load balancer)
    the app sees http://internal-host, which would fail the Destination check."""
    base = urlparse(cfg.base_url)
    https = base.scheme == "https"
    return {
        "https": "on" if https else "off",
        "http_host": base.netloc,  # includes a non-default port, e.g. localhost:8000
        "script_name": path,
        "get_data": get,
        "post_data": post,
    }


def auth_for(cfg: Settings, path: str, get: dict | None = None, post: dict | None = None) -> OneLogin_Saml2_Auth:
    return OneLogin_Saml2_Auth(request_data(cfg, path, get or {}, post or {}), build_settings(cfg))


def safe_relay_state(relay_state: str | None) -> str:
    """Only allow same-site relative paths, to prevent open redirects via RelayState."""
    if relay_state and relay_state.startswith("/") and not relay_state.startswith("//"):
        return relay_state
    return "/me"
