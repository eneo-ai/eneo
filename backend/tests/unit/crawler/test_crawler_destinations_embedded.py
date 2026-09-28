"""The real embedded crawler against local counting HTTP servers: forbidden
destinations produce zero connections, allowed ones are indexed, and the
operator flag flips private networks from allowed to refused."""

import http.server
import socket
import socketserver
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

import crochet
import pytest

# Setup crochet BEFORE importing crawler (module-level @crochet.run_in_reactor).
crochet.setup()

from eneo.crawler.crawler import Crawler  # noqa: E402
from eneo.main.exceptions import CrawlerException  # noqa: E402
from eneo.websites.domain.crawl_run import CrawlType  # noqa: E402

# Third-party parser deprecation noise on older lockfiles is not what these
# tests verify; pytest.ini turns warnings into errors.
pytestmark = pytest.mark.filterwarnings(
    "ignore:The 'strip_cdata' option:DeprecationWarning"
)


def _private_ip() -> str | None:
    """A non-loopback address of this host; loopback is always refused."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ip.startswith("127.") else ip


class _Server:
    """Counting HTTP server bound to all interfaces."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.paths.append(self.path)
                if self.path == "/redirect-loopback":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{server.port}/")
                    self.end_headers()
                    return
                if self.path == "/sitemap.xml":
                    body = (
                        b'<?xml version="1.0"?>'
                        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        + f"<url><loc>http://{server.ip}:{server.port}/a</loc></url>".encode()
                        + f"<url><loc>http://127.0.0.1:{server.port}/b</loc></url>".encode()
                        + b"</urlset>"
                    )
                    self._send(body, "application/xml")
                    return
                self._send(
                    b"<html><title>t</title><body>MARKER</body></html>", "text/html"
                )

            def _send(self, body: bytes, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args, **kwargs):
                pass

        self._httpd = socketserver.TCPServer(("0.0.0.0", 0), Handler)
        self.port = self._httpd.server_address[1]
        self.ip = _private_ip() or "127.0.0.1"
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


@pytest.fixture
def block_private():
    state = {"value": False}
    with patch("eneo.crawler.crawler.get_settings") as get_settings:
        get_settings.side_effect = lambda: SimpleNamespace(
            crawler_block_private_networks=state["value"]
        )
        yield state


async def _crawl(url: str, **kwargs) -> tuple[str | None, int | None]:
    try:
        async with Crawler().crawl(url=url, **kwargs) as crawl:
            return " ".join(p.content for p in crawl.pages), crawl.download_error_count
    except CrawlerException:
        return None, None


async def test_file_scheme_is_never_fetched(block_private):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("FILE_MARKER")
    text, _ = await _crawl(f"file://{f.name}")
    assert text is None


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
async def test_loopback_is_refused_without_connecting(server, block_private, host):
    text, _ = await _crawl(f"http://{host}:{server.port}/")
    assert text is None
    assert server.paths == []


async def test_private_address_is_crawled_by_default(server, block_private):
    if server.ip == "127.0.0.1":
        pytest.skip("no non-loopback interface available")
    text, errors = await _crawl(f"http://{server.ip}:{server.port}/")
    assert text is not None and "MARKER" in text
    assert errors == 0


async def test_redirect_to_loopback_is_not_followed(server, block_private):
    if server.ip == "127.0.0.1":
        pytest.skip("no non-loopback interface available")
    text, errors = await _crawl(f"http://{server.ip}:{server.port}/redirect-loopback")
    assert text is None
    # The refusal counts as a download failure (content preservation), but
    # only once: it is skipped, not retried.
    assert errors is None  # no pages at all -> crawl reported as failed
    # Only the redirect itself (and robots.txt) may be fetched; the loopback
    # target is never requested.
    assert "/redirect-loopback" in server.paths
    assert set(server.paths) <= {"/redirect-loopback", "/robots.txt"}


async def test_sitemap_entry_on_loopback_is_skipped_and_counted(server, block_private):
    if server.ip == "127.0.0.1":
        pytest.skip("no non-loopback interface available")
    text, errors = await _crawl(
        f"http://{server.ip}:{server.port}/sitemap.xml", crawl_type=CrawlType.SITEMAP
    )
    assert text is not None and "MARKER" in text
    assert "/a" in server.paths
    assert "/b" not in server.paths
    assert errors is not None and errors > 0


async def test_block_private_networks_refuses_private_address(server, block_private):
    if server.ip == "127.0.0.1":
        pytest.skip("no non-loopback interface available")
    block_private["value"] = True
    text, _ = await _crawl(f"http://{server.ip}:{server.port}/")
    assert text is None
    assert server.paths == []
