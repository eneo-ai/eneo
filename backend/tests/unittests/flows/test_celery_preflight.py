from __future__ import annotations

import pytest

from intric.flows.runtime import celery_preflight


def test_preflight_reports_missing_document_modules(monkeypatch: pytest.MonkeyPatch):
    def fake_find_spec(module_name: str) -> object | None:
        return None if module_name == "weasyprint" else object()

    monkeypatch.setattr(
        celery_preflight.importlib.util,
        "find_spec",
        fake_find_spec,
    )

    with pytest.raises(celery_preflight.FlowRuntimePreflightError) as exc_info:
        celery_preflight._verify_required_modules()

    assert "weasyprint" in str(exc_info.value)
    assert "rebuild the backend image" in str(exc_info.value)


def test_preflight_runs_pdf_and_docx_smoke_tests(monkeypatch: pytest.MonkeyPatch):
    called: list[str] = []

    def fake_verify_modules() -> None:
        called.append("modules")

    def fake_verify_pdf() -> None:
        called.append("pdf")

    def fake_verify_docx() -> None:
        called.append("docx")

    monkeypatch.setattr(
        celery_preflight, "_verify_required_modules", fake_verify_modules
    )
    monkeypatch.setattr(celery_preflight, "_verify_pdf_renderer", fake_verify_pdf)
    monkeypatch.setattr(celery_preflight, "_verify_docx_renderer", fake_verify_docx)
    monkeypatch.setattr(
        celery_preflight,
        "configure_weasyprint_dependency_logging",
        lambda: called.append("logging"),
    )

    celery_preflight.run_preflight()

    assert called == ["logging", "modules", "pdf", "docx"]


def test_preflight_wraps_renderer_smoke_failures(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(celery_preflight, "_verify_required_modules", lambda: None)
    monkeypatch.setattr(
        celery_preflight,
        "_verify_pdf_renderer",
        lambda: (_ for _ in ()).throw(RuntimeError("missing pango")),
    )
    monkeypatch.setattr(
        celery_preflight,
        "_verify_docx_renderer",
        lambda: None,
    )
    monkeypatch.setattr(
        celery_preflight,
        "configure_weasyprint_dependency_logging",
        lambda: None,
    )

    with pytest.raises(celery_preflight.FlowRuntimePreflightError) as exc_info:
        celery_preflight.run_preflight()

    assert "missing pango" in str(exc_info.value)
    assert "document renderer native dependencies" in str(exc_info.value)


def test_preflight_main_exits_with_status_one_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    monkeypatch.setattr(
        celery_preflight,
        "run_preflight",
        lambda: (_ for _ in ()).throw(
            celery_preflight.FlowRuntimePreflightError("boom")
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        celery_preflight.main()

    assert exc_info.value.code == 1
    assert "boom" in capsys.readouterr().err
