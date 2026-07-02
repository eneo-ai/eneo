from __future__ import annotations

import importlib.util
import io
import sys
from importlib import import_module
from typing import Protocol, cast

from eneo.flows.runtime.document_rendering.weasyprint_renderer import (
    configure_weasyprint_dependency_logging,
)

_REQUIRED_DOCUMENT_MODULES = ("weasyprint", "docx")
_PDF_SMOKE_HTML = (
    "<!doctype html>"
    "<html lang='sv'>"
    "<head><meta charset='utf-8'><title>Flow PDF preflight</title></head>"
    "<body><p>ok</p></body>"
    "</html>"
)


class FlowRuntimePreflightError(RuntimeError):
    pass


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
    def __call__(self, *, string: str) -> _WeasyPrintHtmlDocument: ...


def run_preflight() -> None:
    configure_weasyprint_dependency_logging()
    _verify_required_modules()
    try:
        _verify_pdf_renderer()
        _verify_docx_renderer()
    except Exception as exc:
        raise FlowRuntimePreflightError(
            "Flow runtime document renderer preflight failed: "
            f"{exc.__class__.__name__}: {exc}\n"
            "Rebuild the backend image and verify the document renderer native "
            "dependencies are installed."
        ) from exc


def _verify_required_modules() -> None:
    missing = [
        module_name
        for module_name in _REQUIRED_DOCUMENT_MODULES
        if importlib.util.find_spec(module_name) is None
    ]
    if not missing:
        return
    raise FlowRuntimePreflightError(
        "Missing flow runtime dependencies in worker environment: "
        + ", ".join(missing)
        + "\nInstall backend dependencies (for example `uv sync`) or rebuild the "
        "backend image before starting the Celery flow worker."
    )


def _verify_pdf_renderer() -> None:
    pdf = _load_weasyprint_html_factory()(string=_PDF_SMOKE_HTML).write_pdf()
    if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF-"):
        raise RuntimeError("WeasyPrint did not produce a valid PDF blob")


def _verify_docx_renderer() -> None:
    from docx import Document

    buffer = io.BytesIO()
    Document().save(buffer)
    if not buffer.getvalue().startswith(b"PK"):
        raise RuntimeError("python-docx did not produce a valid DOCX blob")


def _load_weasyprint_html_factory() -> _HtmlFactory:
    weasyprint = import_module("weasyprint")
    return cast(_HtmlFactory, getattr(weasyprint, "HTML"))


def main() -> None:
    try:
        run_preflight()
    except FlowRuntimePreflightError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
