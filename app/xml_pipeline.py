"""Parse, validate and transform structured content.

All XML enters through `parse()`, which uses a hardened parser: no external
entities, no DTD loading, no network access. That blocks XXE attacks, which
matter whenever you accept XML from a customer system or a webhook.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

from lxml import etree

from .config import ROOT

SCHEMA_PATH = ROOT / "schemas" / "article.xsd"
TRANSFORMS = ROOT / "transforms"

_SAFE_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    remove_blank_text=True,
    huge_tree=False,
)


class XMLInputError(ValueError):
    """Input is not well-formed XML."""


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]


def parse(xml: str | bytes) -> etree._ElementTree:
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    try:
        return etree.ElementTree(etree.fromstring(data, parser=_SAFE_PARSER))
    except etree.XMLSyntaxError as exc:
        raise XMLInputError(f"Not well-formed XML: {exc}") from exc


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    return etree.XMLSchema(_load_trusted(SCHEMA_PATH))


@cache
def _xslt(name: str) -> etree.XSLT:
    path = TRANSFORMS / name
    if not path.is_file():
        raise FileNotFoundError(f"Unknown transform: {name}")
    return etree.XSLT(_load_trusted(path))


def _load_trusted(path: Path) -> etree._Element:
    """Load one of our own schema/stylesheet files.

    Read with Python, not by handing libxml2 a file path: xmlsec (pulled in by
    python3-saml) installs restrictive global XSLT security settings, and after
    the first transform libxml2 refuses to open files from disk in this process
    ("XMLSyntaxError: <no detail available>"). Parsing bytes avoids libxml2 file I/O.
    """
    return etree.fromstring(path.read_bytes(), base_url=str(path))


def validate(doc: etree._ElementTree) -> ValidationResult:
    """Validate against the article schema, returning every error (not just the first)."""
    schema = _schema()
    ok = schema.validate(doc)
    errors = [f"line {e.line}: {e.message}" for e in schema.error_log] if not ok else []
    return ValidationResult(ok, errors)


def transform(doc: etree._ElementTree, name: str, **params: str) -> etree._XSLTResultTree:
    """Apply a stylesheet from transforms/. String params are quoted for XSLT."""
    xslt = _xslt(name)
    quoted = {k.replace("_", "-"): etree.XSLT.strparam(v) for k, v in params.items()}
    return xslt(doc, **quoted)


def to_html(doc: etree._ElementTree) -> str:
    return str(transform(doc, "article_to_html.xsl"))


def to_feed_item(doc: etree._ElementTree, base_url: str) -> str | None:
    """RSS <item> for syndication, or None for drafts (the stylesheet emits nothing)."""
    result = transform(doc, "article_to_feed.xsl", base_url=base_url)
    if result.getroot() is None:
        return None
    return etree.tostring(result, pretty_print=True, encoding="unicode")


def canonical_bytes(doc: etree._ElementTree) -> bytes:
    """C14N form, so formatting/whitespace differences don't change the checksum."""
    return etree.tostring(doc, method="c14n")


def checksum(doc: etree._ElementTree) -> str:
    return hashlib.sha256(canonical_bytes(doc)).hexdigest()


def read(path: Path) -> etree._ElementTree:
    return parse(path.read_bytes())
