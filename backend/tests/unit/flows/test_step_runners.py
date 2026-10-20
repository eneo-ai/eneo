"""Document steps: the provider call they build and the file they accept."""

import base64
import io
import zipfile

import pytest

from eneo.flows.definition import DocumentStep
from eneo.flows.step_runners import (
    CREATE_DOCUMENT_TOOL,
    FILL_TEMPLATE_TOOL,
    STEP_DOCUMENT_FAILED,
    STEP_TEMPLATE_ERROR,
    FlowStepError,
    document_from_result,
    document_tool_arguments,
    expected_document_mime_types,
)
from eneo.flows.templating import StepOutput, TemplateContext
from eneo.mcp_servers.domain.entities.mcp_server import DOCX_MIME_TYPE, PDF_MIME_TYPE


def _context() -> TemplateContext:
    context = TemplateContext(form={"malgrupp": "ledning"})
    context.steps["summera"] = StepOutput(text="Allt gick bra.", value=None)
    context.previous = "Allt gick bra."
    return context


def minimal_docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"></Types>',
        )
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def _file_block(data: bytes, mime_type: str, filename: str) -> dict:
    return {
        "type": "file",
        "data": base64.b64encode(data).decode(),
        "mime_type": mime_type,
        "filename": filename,
    }


class TestDocumentToolArguments:
    def test_content_step_renders_a_create_document_call(self):
        step = DocumentStep(
            key="doc",
            name="Sammanfattning",
            format="pdf",
            title="Rapport för {{form.malgrupp}}",
            filename="rapport-{{form.malgrupp}}",
            content="# Rapport\n\n{{steps.summera}}",
        )
        tool, arguments = document_tool_arguments(step, _context())
        assert tool == CREATE_DOCUMENT_TOOL
        assert arguments == {
            "filename": "rapport-ledning",
            "title": "Rapport för ledning",
            "format": "pdf",
            "content": "# Rapport\n\nAllt gick bra.",
            "language": "sv",
        }

    def test_title_defaults_to_the_step_name(self):
        step = DocumentStep(key="doc", name="Beslut", content="{{previous}}")
        _, arguments = document_tool_arguments(step, _context())
        assert arguments["title"] == "Beslut"
        assert "filename" not in arguments

    def test_template_step_fills_the_form_with_rendered_values(self):
        step = DocumentStep(
            key="doc",
            name="Protokoll",
            template_file_id="eneo-file:0123456789abcdef0123456789abcdef",
            values={"namn": "{{form.malgrupp}}", "text": "{{steps.summera}}"},
        )
        tool, arguments = document_tool_arguments(
            step, _context(), template=("https://eneo/t?token=x", "mall.docx")
        )
        assert tool == FILL_TEMPLATE_TOOL
        assert arguments == {
            "template": {"url": "https://eneo/t?token=x", "filename": "mall.docx"},
            "values": {"namn": "ledning", "text": "Allt gick bra."},
        }

    def test_a_template_error_names_the_field(self):
        step = DocumentStep(
            key="doc", name="Doc", content="{{steps.missing}}", title="ok"
        )
        with pytest.raises(FlowStepError) as exc:
            document_tool_arguments(step, _context())
        assert exc.value.code == STEP_TEMPLATE_ERROR
        assert "step 'doc' content" in exc.value.message


class TestExpectedMimeTypes:
    def test_content_step_expects_its_format(self):
        step = DocumentStep(key="d", name="D", content="x", format="pdf")
        assert expected_document_mime_types(step, None) == {PDF_MIME_TYPE}

    def test_template_step_expects_the_template_format(self):
        step = DocumentStep(key="d", name="D", template_file_id="0" * 32)
        assert expected_document_mime_types(step, "Mall.DOCX") == {DOCX_MIME_TYPE}
        assert expected_document_mime_types(step, "mall.txt") == {"text/plain"}


class TestDocumentFromResult:
    step = DocumentStep(key="doc", name="Rapport", content="x")

    def test_accepts_the_admitted_file_of_the_expected_type(self):
        data = minimal_docx()
        result = {
            "content": [
                {"type": "text", "text": "Created Rapport.docx"},
                _file_block(data, DOCX_MIME_TYPE, "Rapport.docx"),
            ]
        }
        document = document_from_result(
            result, step=self.step, expected_mime_types=frozenset({DOCX_MIME_TYPE})
        )
        assert document.filename == "Rapport.docx"
        assert document.mime_type == DOCX_MIME_TYPE
        assert document.data == data

    def test_an_error_result_fails_with_the_provider_text(self):
        result = {
            "is_error": True,
            "content": [{"type": "text", "text": "VALUES_REQUIRED: pass values"}],
        }
        with pytest.raises(FlowStepError) as exc:
            document_from_result(
                result, step=self.step, expected_mime_types=frozenset({DOCX_MIME_TYPE})
            )
        assert exc.value.code == STEP_DOCUMENT_FAILED
        assert "VALUES_REQUIRED" in exc.value.message

    def test_a_file_of_another_type_does_not_count(self):
        result = {"content": [_file_block(b"%PDF-1.4 %%EOF", PDF_MIME_TYPE, "x.pdf")]}
        with pytest.raises(FlowStepError) as exc:
            document_from_result(
                result, step=self.step, expected_mime_types=frozenset({DOCX_MIME_TYPE})
            )
        assert exc.value.code == STEP_DOCUMENT_FAILED

    def test_bytes_that_are_not_the_declared_document_are_rejected(self):
        result = {"content": [_file_block(b"not a zip", DOCX_MIME_TYPE, "x.docx")]}
        with pytest.raises(FlowStepError) as exc:
            document_from_result(
                result, step=self.step, expected_mime_types=frozenset({DOCX_MIME_TYPE})
            )
        assert exc.value.code == STEP_DOCUMENT_FAILED
        assert "cannot keep" in exc.value.message


class TestFunctionSteps:
    def test_arguments_render_every_string_including_nested_ones(self):
        from eneo.flows.definition import FunctionStep
        from eneo.flows.step_runners import render_arguments

        step = FunctionStep(
            key="search",
            name="Sök",
            purpose="web_search",
            tool="search",
            arguments={
                "query": "{{form.malgrupp}} {{steps.summera}}",
                "options": {"limit": 5, "sites": ["{{form.malgrupp}}.se"]},
            },
        )
        rendered = render_arguments(step, step.arguments, _context())
        assert rendered == {
            "query": "ledning Allt gick bra.",
            "options": {"limit": 5, "sites": ["ledning.se"]},
        }

    def test_a_tool_result_becomes_text_value_and_files(self):
        from eneo.flows.definition import FunctionStep
        from eneo.flows.step_runners import function_outcome

        step = FunctionStep(
            key="chart", name="Diagram", purpose="charts", tool="create_chart"
        )
        png = base64.b64encode(b"\x89PNG fake").decode()
        result = {
            "content": [
                {"type": "text", "text": '{"series": 2}'},
                {"type": "image", "data": png, "mime_type": "image/png"},
            ]
        }
        outcome = function_outcome(result, step=step)
        assert outcome.output_payload == {
            "text": '{"series": 2}',
            "value": {"series": 2},
        }
        assert [d.filename for d in outcome.documents] == ["chart-1.png"]
        assert outcome.documents[0].mime_type == "image/png"

    def test_an_error_result_fails_the_step_with_the_tool_text(self):
        from eneo.flows.definition import FunctionStep
        from eneo.flows.step_runners import STEP_FUNCTION_FAILED, function_outcome

        step = FunctionStep(key="s", name="S", purpose="web_search", tool="search")
        with pytest.raises(FlowStepError) as exc:
            function_outcome(
                {"is_error": True, "content": [{"type": "text", "text": "quota"}]},
                step=step,
            )
        assert exc.value.code == STEP_FUNCTION_FAILED
        assert "quota" in exc.value.message
