from pathlib import Path

import pytest
from lxml import etree

from app import xml_pipeline

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_valid_article_passes():
    assert xml_pipeline.validate(xml_pipeline.read(SAMPLES / "article.xml")).valid


def test_invalid_article_reports_every_error():
    result = xml_pipeline.validate(xml_pipeline.read(SAMPLES / "invalid_article.xml"))
    assert not result.valid
    joined = " ".join(result.errors)
    assert "status" in joined and "id" in joined  # bad enum + bad id pattern
    assert len(result.errors) >= 3


def test_malformed_xml_raises():
    with pytest.raises(xml_pipeline.XMLInputError):
        xml_pipeline.parse("<article><title>unclosed</article>")


def test_xxe_entities_are_not_expanded(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    payload = f"""<?xml version="1.0"?>
<!DOCTYPE a [<!ENTITY x SYSTEM "file://{secret}">]>
<article id="xxe-test" status="draft"><title>&x;</title></article>"""
    doc = xml_pipeline.parse(payload)
    assert "TOP-SECRET" not in etree.tostring(doc, encoding="unicode")


def test_html_transform_renders_title_and_author_list():
    html = xml_pipeline.to_html(xml_pipeline.read(SAMPLES / "article.xml"))
    assert "<h1>Why Print Costs Rose This Quarter</h1>" in html
    assert "Ada Mensah and Tom Reilly" in html


def test_feed_transform_builds_rss_item():
    item = xml_pipeline.to_feed_item(xml_pipeline.read(SAMPLES / "article.xml"), "https://kit.test")
    root = etree.fromstring(item.encode())
    assert root.tag == "item"
    assert root.findtext("link") == "https://kit.test/articles/quarterly-print-costs.html"
    assert [c.text for c in root.findall("category")] == ["operations", "print"]


def test_feed_transform_skips_drafts():
    doc = xml_pipeline.read(SAMPLES / "article.xml")
    doc.getroot().set("status", "draft")
    assert xml_pipeline.to_feed_item(doc, "https://kit.test") is None


def test_checksum_ignores_formatting():
    a = xml_pipeline.parse('<article id="abc" status="draft"><title>T</title></article>')
    b = xml_pipeline.parse('<article  status="draft"   id="abc">\n  <title>T</title>\n</article>')
    assert xml_pipeline.checksum(a) == xml_pipeline.checksum(b)


def test_all_transforms_load_after_saml_library_and_a_prior_transform():
    """Regression: with xmlsec loaded, libxml2 stopped opening files after the first
    transform, so the second stylesheet failed with '<no detail available>'.

    Runs in a fresh interpreter: the bug only appears when xmlsec is imported
    before any XSLT has run, which earlier tests in this process would mask."""
    import subprocess
    import sys

    script = (
        "import xmlsec\n"
        "from pathlib import Path\n"
        "from app import xml_pipeline as x\n"
        "doc = x.read(Path('samples/article.xml'))\n"
        "x.to_html(doc)\n"
        "assert x.to_feed_item(doc, 'https://kit.test')\n"
        "assert x.validate(doc).valid\n"
    )
    root = SAMPLES.parent
    r = subprocess.run([sys.executable, "-c", script], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


def test_transform_endpoints_over_http(client):
    body = (SAMPLES / "article.xml").read_bytes()
    assert client.post("/xml/transform/html", content=body).status_code == 200
    r = client.post("/xml/transform/feed", content=body)
    assert r.status_code == 200 and b"<item>" in r.content
    assert client.post("/xml/transform/feed", content=(SAMPLES / "invalid_article.xml").read_bytes()).status_code == 422
    assert client.post("/xml/transform/pdf", content=body).status_code == 404


def test_legacy_transform_maps_fields():
    export = xml_pipeline.read(SAMPLES / "legacy_export.xml")
    doc = etree.ElementTree(export.getroot().find("doc"))
    import copy
    article = xml_pipeline.transform(etree.ElementTree(copy.deepcopy(doc.getroot())), "legacy_to_article.xsl")
    root = article.getroot()
    assert root.get("id") == "l-1001" and root.get("status") == "published"
    assert root.findtext("published") == "2026-09-14"
    assert [a.text for a in root.findall("byline/author")] == ["Ada Mensah", "Priya Nair"]
    assert [t.text for t in root.findall("tags/tag")] == ["workflow", "structured content"]
    assert xml_pipeline.validate(article).valid
