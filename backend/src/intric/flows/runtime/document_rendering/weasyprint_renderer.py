from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import import_module
from typing import NoReturn, Protocol, Sequence, cast

from intric.flows.runtime.document_rendering.blocks import DocumentBlock
from intric.flows.runtime.document_rendering.html_blocks import (
    blocks_to_html_document,
)
from intric.flows.runtime.document_rendering.renderers import RenderedDocument

_PDF_MIMETYPE = "application/pdf"
_NOISY_WEASYPRINT_LOGGERS = (
    "fontTools",
    "fontTools.subset",
    "weasyprint",
    "weasyprint.progress",
)
_DOCUMENT_CSS = """
@page {
  size: A4;
  margin: 20mm 18mm;
}

html {
  color: #1f2328;
  font-family: "DejaVu Sans", "Liberation Sans", sans-serif;
  font-size: 11pt;
  line-height: 1.45;
}

body {
  margin: 0;
}

.document {
  overflow-wrap: anywhere;
}

h1,
h2,
h3,
h4 {
  color: #0f172a;
  font-weight: 700;
  line-height: 1.2;
  margin: 0 0 8pt;
  page-break-after: avoid;
}

h1 {
  font-size: 22pt;
  margin-top: 0;
}

h2 {
  font-size: 16pt;
  margin-top: 18pt;
}

h3 {
  font-size: 13pt;
  margin-top: 14pt;
}

h4 {
  font-size: 11.5pt;
  margin-top: 12pt;
}

p,
ul,
ol,
pre,
table {
  margin: 0 0 10pt;
}

ul,
ol {
  padding-left: 18pt;
}

li {
  margin: 0 0 3pt;
}

code {
  background: #f6f8fa;
  border-radius: 3pt;
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 0.92em;
  padding: 0.5pt 2pt;
}

pre {
  background: #f6f8fa;
  border: 1px solid #d0d7de;
  border-radius: 4pt;
  font-family: "DejaVu Sans Mono", "Liberation Mono", monospace;
  font-size: 9.5pt;
  padding: 8pt;
  white-space: pre-wrap;
}

pre code {
  background: transparent;
  border-radius: 0;
  padding: 0;
}

s {
  color: #57606a;
}

table {
  border-collapse: collapse;
  table-layout: fixed;
  width: 100%;
}

thead {
  display: table-header-group;
}

tr {
  page-break-inside: avoid;
}

th,
td {
  border: 1px solid #d8dee4;
  padding: 5pt 6pt;
  text-align: left;
  vertical-align: top;
}

th {
  background: #f6f8fa;
  color: #111827;
  font-weight: 700;
}

.block-spacer {
  height: 4pt;
}
"""


class _WeasyPrintHtmlDocument(Protocol):
    def write_pdf(
        self,
        target: object | None = None,
        zoom: int = 1,
        finisher: object | None = None,
        font_config: object | None = None,
        counter_style: object | None = None,
        **options: object,
    ) -> bytes | None: ...


class _HtmlFactory(Protocol):
    def __call__(
        self,
        *,
        string: str,
        media_type: str,
        url_fetcher: Callable[..., NoReturn],
    ) -> _WeasyPrintHtmlDocument: ...


class _CssFactory(Protocol):
    def __call__(self, *, string: str, font_config: object) -> object: ...


class _FontConfigurationFactory(Protocol):
    def __call__(self) -> object: ...


class WeasyPrintDocumentRenderer:
    output_type = "pdf"

    def render(
        self,
        blocks: Sequence[DocumentBlock],
        *,
        step_order: int,
    ) -> RenderedDocument:
        configure_weasyprint_dependency_logging()
        html_class, css_class, font_config_class = _load_weasyprint_api()
        font_config = font_config_class()
        html = blocks_to_html_document(
            blocks,
            title=f"Flow step {step_order} output",
        )
        pdf_bytes = html_class(
            string=html,
            media_type="print",
            url_fetcher=_deny_external_fetch,
        ).write_pdf(
            stylesheets=[css_class(string=_DOCUMENT_CSS, font_config=font_config)],
            font_config=font_config,
            # Keep the PDF structurally tagged without claiming PDF/UA conformance
            # before we have a validator in CI.
            pdf_tags=True,
            srgb=True,
        )
        if pdf_bytes is None:
            raise RuntimeError("WeasyPrint did not return PDF bytes")
        return RenderedDocument(
            blob=bytes(pdf_bytes),
            mimetype=_PDF_MIMETYPE,
            filename=f"step_{step_order}_output.pdf",
        )


def configure_weasyprint_dependency_logging() -> None:
    for logger_name in _NOISY_WEASYPRINT_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _load_weasyprint_api() -> tuple[
    _HtmlFactory,
    _CssFactory,
    _FontConfigurationFactory,
]:
    weasyprint = import_module("weasyprint")
    font_module = import_module("weasyprint.text.fonts")
    return (
        cast(_HtmlFactory, getattr(weasyprint, "HTML")),
        cast(_CssFactory, getattr(weasyprint, "CSS")),
        cast(_FontConfigurationFactory, getattr(font_module, "FontConfiguration")),
    )


def _deny_external_fetch(
    url: str,
    *args: object,
    **kwargs: object,
) -> NoReturn:
    raise _url_fetching_error(f"External PDF resource loading is disabled: {url}")


def _url_fetching_error(message: str) -> BaseException:
    try:
        error_type = getattr(
            import_module("weasyprint.urls"),
            "URLFetchingError",
        )
    except (ImportError, AttributeError):
        return OSError(message)
    return cast(type[BaseException], error_type)(message)
