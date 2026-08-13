from eneo.crawler.extraction import extract_html, is_in_scope, normalize_url


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
    assert page.file_links == ("https://example.se/service/documents/formular.pdf",)


def test_normalize_url_removes_fragments_and_default_ports() -> None:
    assert (
        normalize_url("../info?lang=sv#section", base_url="HTTPS://Example.SE:443/a/b/")
        == "https://example.se/a/info?lang=sv"
    )
    assert normalize_url("mailto:test@example.se") is None


def test_scope_requires_same_host_and_path_segment() -> None:
    seed = "https://example.se/service"

    assert is_in_scope("https://example.se/service", seed)
    assert is_in_scope("https://example.se/service/skola", seed)
    assert not is_in_scope("https://example.se/services", seed)
    assert not is_in_scope("https://other.example/service", seed)
