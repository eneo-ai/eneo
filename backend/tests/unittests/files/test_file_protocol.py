from io import BytesIO

import pytest
from docx import Document
from fastapi import UploadFile

from intric.files.file_models import FileType
from intric.files.file_protocol import FileProtocol
from intric.files.file_size_service import FileSizeService
from intric.files.image import ImageExtractor
from intric.files.text import TextExtractor
from intric.main.exceptions import FileNotSupportedException


def _build_docx_bytes(*paragraphs: str) -> bytes:
    buffer = BytesIO()
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    document.save(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_docx_template_to_domain_preserves_blob_and_extracted_text() -> None:
    protocol = FileProtocol(
        file_size_service=FileSizeService(),
        text_extractor=TextExtractor(),
        image_extractor=ImageExtractor(),
    )
    docx_bytes = _build_docx_bytes("Bakgrund", "{{bakgrund}}")
    upload = UploadFile(
        filename="rapport.docx",
        file=BytesIO(docx_bytes),
        headers={
            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        },
    )

    file = await protocol.docx_template_to_domain(upload)

    assert file.file_type == FileType.DOCUMENT
    assert file.blob == docx_bytes
    assert "Bakgrund" in (file.text or "")
    assert "{{bakgrund}}" in (file.text or "")
    assert file.mimetype == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@pytest.mark.asyncio
async def test_docx_template_to_domain_rejects_macro_enabled_extensions() -> None:
    protocol = FileProtocol(
        file_size_service=FileSizeService(),
        text_extractor=TextExtractor(),
        image_extractor=ImageExtractor(),
    )
    upload = UploadFile(
        filename="rapport.docm",
        file=BytesIO(b"fake"),
        headers={
            "content-type": "application/vnd.ms-word.document.macroEnabled.12"
        },
    )

    with pytest.raises(
        FileNotSupportedException,
        match="DOCX templates must use the .docx format",
    ):
        await protocol.docx_template_to_domain(upload)
