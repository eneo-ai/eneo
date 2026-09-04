from urllib.parse import urlsplit

import pytest

from eneo.crawler.extraction import (
    extract_html,
    is_in_scope,
    is_page_link,
    is_same_origin,
    normalize_url,
)


def test_extract_html_prefers_main_content_but_discovers_navigation_links() -> None:
    page = extract_html(
        """
        <html>
          <head><title>Kommunens sida</title></head>
          <body>
            <nav><a href="/kontakt">Kontakt</a></nav>
            <main>
              <h1>Ansök om skolplats</h1>
              <p>Ansökan är öppen till den 15 september.</p>
              <a href="documents/formular.pdf">Blankett</a>
              <a href="/api/data.json">Data</a>
              <a href="/images/photo.jpg">Bild</a>
            </main>
            <footer>Sidfot som inte ska indexeras</footer>
          </body>
        </html>
        """,
        "https://example.se/service/skola",
    )

    assert page.title == "Kommunens sida"
    assert "Ansök om skolplats" in page.content
    assert "15 september" in page.content
    assert "Sidfot" not in page.content
    assert page.links == ("https://example.se/kontakt",)
    assert page.file_links == (
        "https://example.se/service/documents/formular.pdf",
        "https://example.se/api/data.json",
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.se/image.jpg", False),
        ("https://example.se/image%2Ejpg", False),
        ("https://example.se/document.pdf", False),
        ("https://example.se/app.webmanifest", False),
        ("https://example.se/page", True),
        ("https://example.se/page.html", True),
        ("https://example.se/page.xhtml", True),
        ("https://example.se/data.json", True),
        ("https://example.se/page.php", True),
        ("https://example.se/page.aspx", True),
    ],
)
def test_page_link_classification_is_deterministic(url: str, expected: bool) -> None:
    assert is_page_link(url) is expected


def test_normalize_url_removes_fragments_and_default_ports() -> None:
    assert (
        normalize_url("../info?lang=sv#section", base_url="HTTPS://Example.SE:443/a/b/")
        == "https://example.se/a/info?lang=sv"
    )
    assert normalize_url("mailto:test@example.se") is None


@pytest.mark.parametrize(
    ("url", "expected", "port"),
    [
        ("https://[2001:DB8::1]/path#part", "https://[2001:db8::1]/path", None),
        ("https://[2001:db8::1]:443/path", "https://[2001:db8::1]/path", None),
        ("http://[2001:db8::1]:80/path", "http://[2001:db8::1]/path", None),
        ("https://[2001:db8::1]:8443/path", "https://[2001:db8::1]:8443/path", 8443),
    ],
)
def test_ipv6_url_normalization_preserves_a_parseable_origin(
    url: str, expected: str, port: int | None
) -> None:
    normalized = normalize_url(url)
    assert normalized == expected
    assert normalized is not None
    parsed = urlsplit(normalized)
    assert parsed.hostname == "2001:db8::1"
    assert parsed.port == port
    assert normalize_url(normalized) == normalized

    child = normalize_url("path/child", base_url=normalized)
    assert child is not None
    assert is_in_scope(child, normalized)
    assert is_same_origin(child, normalized)
    assert not is_same_origin(child.replace("::1", "::2"), normalized)
    assert not is_same_origin(child, "https://[2001:db8::1]:9443/path")


def test_scope_requires_same_host_and_path_segment() -> None:
    seed = "https://example.se/service"

    assert is_in_scope("https://example.se/service", seed)
    assert is_in_scope("https://example.se/service/skola", seed)
    assert not is_in_scope("https://example.se/services", seed)
    assert not is_in_scope("https://other.example/service", seed)
