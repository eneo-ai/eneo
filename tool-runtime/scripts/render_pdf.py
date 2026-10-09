"""Renders one HTML document to a tagged PDF with WeasyPrint.

Run by the tool runtime's sandbox child as ``python3 -I -B render_pdf.py <job.json>``. The
job names an HTML file, its stylesheet and the output path, all inside one directory the
runtime made for this render. Nothing outside that directory is fetched: the URL fetcher
refuses every other location, so a document cannot pull in resources from the network or
the filesystem. Prints ``{"pages": n}`` on success.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    base = Path(job["base_dir"]).resolve()
    html_path = Path(job["html_path"]).resolve()
    css_path = Path(job["css_path"]).resolve()
    output = Path(job["output_path"]).resolve()
    for path in (html_path, css_path, output):
        if base not in path.parents:
            raise SystemExit(f"{path} is outside the render directory")

    for name in ("fontTools", "fontTools.subset", "weasyprint", "weasyprint.progress"):
        logging.getLogger(name).setLevel(logging.ERROR)

    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration
    from weasyprint.urls import URLFetcherResponse, URLFetchingError

    # Served without urllib: the default fetcher consults /etc/mime.types, which the
    # sandbox does not expose, and a failed load drops the image silently.
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".css": "text/css",
        ".html": "text/html",
    }

    def fetch(url: str, *args: object, **kwargs: object) -> URLFetcherResponse:
        parsed = urlparse(url)
        if parsed.scheme != "file":
            raise URLFetchingError(f"Only the document's own files may be loaded: {url}")
        target = Path(unquote(parsed.path)).resolve()
        if base not in target.parents:
            raise URLFetchingError(f"Only the document's own files may be loaded: {url}")
        media_type = media_types.get(target.suffix.lower())
        if media_type is None:
            raise URLFetchingError(f"Unsupported file type: {url}")
        return URLFetcherResponse(
            url, body=target.open("rb"), headers={"Content-Type": media_type}
        )

    fonts = FontConfiguration()
    document = HTML(
        filename=str(html_path),
        base_url=base.as_uri() + "/",
        url_fetcher=fetch,
    ).render(
        stylesheets=[CSS(filename=str(css_path), font_config=fonts, url_fetcher=fetch)],
        font_config=fonts,
    )
    options = {
        "pdf_tags": True,
        "srgb": True,
        "optimize_images": True,
        "jpeg_quality": 90,
    }
    if job.get("pdf_variant"):
        options["pdf_variant"] = job["pdf_variant"]
    pdf = document.write_pdf(**options)
    if pdf is None:
        raise SystemExit("WeasyPrint returned no PDF")
    output.write_bytes(pdf)
    print(json.dumps({"pages": len(document.pages)}))
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
