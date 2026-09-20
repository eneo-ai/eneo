import multiprocessing
import os
import signal
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from eneo.files.text import ExtractionError, PdfExtractionLimitExceeded, TextExtractor
from eneo.main.config import get_settings


def _write_pdf(path, page_count):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            "<< /Type /Pages /Kids ["
            + " ".join(f"{4 + i * 2} 0 R" for i in range(page_count))
            + f"] /Count {page_count} >>"
        ).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i in range(page_count):
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R >> >> "
                f"/Contents {5 + i * 2} 0 R >>"
            ).encode()
        )
        stream = b"BT /F1 12 Tf 50 700 Td (\\345) Tj ET"
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    document = b"%PDF-1.4\n"
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(document))
        document += f"{number} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(document)
    document += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    document += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    document += (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(document)
    return path


class _ObservedExtractor(TextExtractor):
    @classmethod
    def _extract_pdf_page(cls, page):
        with Path(page.pdf.stream.name).with_suffix(".pages").open("a") as output:
            output.write(f"{page.page_number}\n")
        return super()._extract_pdf_page(page)


class _RefusingExtractor(TextExtractor):
    @classmethod
    def _extract_pdf_page(cls, page):
        raise PdfExtractionLimitExceeded("extracted_bytes", 11, 10)


def _hanging_page(page):
    Path(page.pdf.stream.name).with_suffix(".pid").write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
    return "late"


def _hanging_child(*args):
    with patch.object(TextExtractor, "_extract_pdf_page", side_effect=_hanging_page):
        TextExtractor._extract_pdf_in_child(*args)


def _crashed_child(*args):
    args[0].with_suffix(".pid").write_text(str(os.getpid()))
    os._exit(17)


def test_pdf_page_limit_refuses_before_reading_any_page(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "flow_pdf_max_pages", 2)
    path = _write_pdf(tmp_path / "many.pdf", 3)

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        _ObservedExtractor.extract_from_pdf(path)

    assert (caught.value.limit, caught.value.measured, caught.value.ceiling) == (
        "pages",
        3,
        2,
    )
    assert not path.with_suffix(".pages").exists()


def test_pdf_byte_limit_includes_utf8_markers_and_page_separators(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(get_settings(), "flow_pdf_max_extracted_bytes", 23)
    path = _write_pdf(tmp_path / "many.pdf", 3)

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        _ObservedExtractor.extract_from_pdf(path)

    assert (caught.value.limit, caught.value.measured, caught.value.ceiling) == (
        "extracted_bytes",
        24,
        23,
    )
    assert path.with_suffix(".pages").read_text() == "1\n2\n"


def test_pdf_at_page_and_byte_limits_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "flow_pdf_max_pages", 2)
    monkeypatch.setattr(get_settings(), "flow_pdf_max_extracted_bytes", 24)
    path = _write_pdf(tmp_path / "exact.pdf", 2)

    assert _ObservedExtractor.extract_from_pdf(path) == "[PAGE 1]\nå\n\n[PAGE 2]\nå"


def test_hanging_pdf_parser_is_killed_and_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "flow_pdf_extraction_timeout_seconds", 2)
    monkeypatch.setattr(
        TextExtractor, "_extract_pdf_in_child", staticmethod(_hanging_child)
    )
    path = _write_pdf(tmp_path / "hang.pdf", 1)
    started = time.monotonic()

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        TextExtractor.extract_from_pdf(path)

    elapsed = time.monotonic() - started
    assert caught.value.limit == "seconds"
    assert caught.value.ceiling == 2
    assert 2 <= caught.value.measured <= elapsed < 3.5
    pid = int(path.with_suffix(".pid").read_text())
    assert all(child.pid != pid for child in multiprocessing.active_children())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_pdf_refusal_bypasses_plain_text_fallback(tmp_path):
    path = _write_pdf(tmp_path / "refusal.pdf", 1)

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        _RefusingExtractor.extract_from_pdf(path)

    assert (caught.value.limit, caught.value.measured, caught.value.ceiling) == (
        "extracted_bytes",
        11,
        10,
    )


def test_pdf_child_crash_is_an_extraction_error_and_is_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(
        TextExtractor, "_extract_pdf_in_child", staticmethod(_crashed_child)
    )
    path = _write_pdf(tmp_path / "crash.pdf", 1)

    with pytest.raises(ExtractionError, match="exited with code 17"):
        TextExtractor.extract_from_pdf(path)

    pid = int(path.with_suffix(".pid").read_text())
    assert all(child.pid != pid for child in multiprocessing.active_children())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_pdf_fixture_preserves_golden_text():
    fixture = (
        Path(__file__).resolve().parents[3]
        / "scripts/fixtures/ai_builder_battle/06_tidigare_beslut.pdf"
    )
    assert TextExtractor.extract_from_pdf(fixture) == (
        "[PAGE 1]\nProtokollsutdrag - Barn- och utbildningsnamndens arbetsutskott\n"
        "Diarienummer: BUN-2026-00037-1\nSammantradesdatum: 2026-02-11\n"
        "Paragraf 11: Ny forskolestruktur i Njurunda\n"
        "Arbetsutskottet foreslar avveckling av Klockarbergets forskola.\n"
        "Forslaget motiveras av minskat barnantal i Njurunda.\n"
        "Beslutet ska forenas med trygg overgangen for barn och personal.\n"
        "Personaltatheten ska i genomsnitt vara hogst 5,0 barn per anstalld.\n"
        "Arkiveringsstampel:\nB\nE\nS\nL\nU\nT\nA\nD"
    )
