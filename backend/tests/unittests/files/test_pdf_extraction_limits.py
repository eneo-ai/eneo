import asyncio
import multiprocessing
import os
import signal
import time
from contextlib import suppress
from dataclasses import replace
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from eneo.files import text
from eneo.files.text import (
    ExtractionError,
    PdfExtractionLimitExceeded,
    PdfExtractionLimits,
    TextExtractor,
)
from eneo.main.config import get_settings

_LIMITS = PdfExtractionLimits(max_pages=10, max_extracted_bytes=1024, timeout_seconds=2)


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


def test_knowledge_pdf_extraction_ignores_flow_ceilings(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "flow_pdf_max_pages", 1)
    monkeypatch.setattr(get_settings(), "flow_pdf_max_extracted_bytes", 1)
    path = _write_pdf(tmp_path / "knowledge.pdf", 2)

    assert (
        TextExtractor().extract(path, "application/pdf") == "[PAGE 1]\nå\n\n[PAGE 2]\nå"
    )


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


class _ControlledExtractor(TextExtractor):
    @classmethod
    def _extract_pdf_page(cls, page):
        path = Path(page.pdf.stream.name)
        path.with_suffix(".pid").write_text(str(os.getpid()))
        while not path.with_suffix(".release").exists():
            time.sleep(0.01)
        return super()._extract_pdf_page(page)


@pytest.fixture
def pdf_capacity(monkeypatch):
    capacity = asyncio.Semaphore(1)
    monkeypatch.setattr(text, "_PDF_EXTRACTION_SEMAPHORE", capacity)
    return capacity


async def _wait_for_parser(path):
    async with asyncio.timeout(2):
        while not path.with_suffix(".pid").exists():
            await asyncio.sleep(0.01)
    return int(path.with_suffix(".pid").read_text())


@pytest.mark.asyncio
async def test_pdf_capacity_serializes_child_processes(tmp_path, pdf_capacity):
    first = _write_pdf(tmp_path / "first.pdf", 1)
    second = _write_pdf(tmp_path / "second.pdf", 1)
    limits = replace(_LIMITS, timeout_seconds=5)
    context = multiprocessing.get_context("spawn")
    tasks = []
    with patch.object(context, "Process", wraps=context.Process) as spawn:
        try:
            tasks.append(
                asyncio.create_task(
                    _ControlledExtractor.extract_from_pdf_async(first, limits=limits)
                )
            )
            first_pid = await _wait_for_parser(first)
            tasks.append(
                asyncio.create_task(
                    _ControlledExtractor.extract_from_pdf_async(second, limits=limits)
                )
            )
            await asyncio.sleep(0.1)
            assert spawn.call_count == 1
            assert not second.with_suffix(".pid").exists()

            first.with_suffix(".release").touch()
            await _wait_for_parser(second)
            with pytest.raises(ProcessLookupError):
                os.kill(first_pid, 0)
            assert spawn.call_count == 2
            second.with_suffix(".release").touch()
            assert await asyncio.gather(*tasks) == ["[PAGE 1]\nå", "[PAGE 1]\nå"]
            assert not pdf_capacity.locked()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_pdf_capacity_timeout_refuses_without_spawning(tmp_path, pdf_capacity):
    path = _write_pdf(tmp_path / "queued.pdf", 1)
    context = multiprocessing.get_context("spawn")
    await pdf_capacity.acquire()
    started = time.monotonic()
    try:
        with patch.object(context, "Process", wraps=context.Process) as spawn:
            async with asyncio.timeout(2):
                with pytest.raises(PdfExtractionLimitExceeded) as caught:
                    await TextExtractor.extract_from_pdf_async(
                        path, limits=replace(_LIMITS, timeout_seconds=1)
                    )
            spawn.assert_not_called()
        assert caught.value.limit == "seconds"
        assert caught.value.ceiling == 1
        assert caught.value.reason == "extraction_capacity"
        assert 1 <= caught.value.measured <= time.monotonic() - started < 1.5
        assert pdf_capacity.locked()
    finally:
        pdf_capacity.release()
    assert (
        await TextExtractor.extract_from_pdf_async(path, limits=_LIMITS)
        == "[PAGE 1]\nå"
    )


@pytest.mark.asyncio
async def test_pdf_cancellation_while_waiting_preserves_capacity(
    tmp_path, pdf_capacity
):
    path = _write_pdf(tmp_path / "cancelled.pdf", 1)
    context = multiprocessing.get_context("spawn")
    await pdf_capacity.acquire()
    task = asyncio.create_task(
        TextExtractor.extract_from_pdf_async(path, limits=_LIMITS)
    )
    try:
        with patch.object(context, "Process", wraps=context.Process) as spawn:
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            spawn.assert_not_called()
        assert pdf_capacity.locked()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pdf_capacity.release()
    assert (
        await TextExtractor.extract_from_pdf_async(path, limits=_LIMITS)
        == "[PAGE 1]\nå"
    )


@pytest.mark.asyncio
async def test_pdf_cancellation_reaps_before_releasing_capacity(tmp_path, pdf_capacity):
    path = _write_pdf(tmp_path / "cancelled.pdf", 1)
    task = asyncio.create_task(
        _ControlledExtractor.extract_from_pdf_async(path, limits=_LIMITS)
    )
    try:
        pid = await _wait_for_parser(path)
        assert pdf_capacity.locked()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not pdf_capacity.locked()
        assert (
            await TextExtractor.extract_from_pdf_async(path, limits=_LIMITS)
            == "[PAGE 1]\nå"
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_pdf_capacity_wait_consumes_extraction_deadline(
    tmp_path, pdf_capacity, monkeypatch
):
    monkeypatch.setattr(
        TextExtractor, "_extract_pdf_in_child", staticmethod(_hanging_child)
    )
    path = _write_pdf(tmp_path / "queued-hang.pdf", 1)
    await pdf_capacity.acquire()

    async def release_capacity():
        await asyncio.sleep(1)
        pdf_capacity.release()

    release = asyncio.create_task(release_capacity())
    started = time.monotonic()
    try:
        with pytest.raises(PdfExtractionLimitExceeded) as caught:
            await TextExtractor.extract_from_pdf_async(path, limits=_LIMITS)
        assert caught.value.limit == "seconds"
        assert 2 <= caught.value.measured <= time.monotonic() - started < 2.75
        assert caught.value.reason is None
        pid = int(path.with_suffix(".pid").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not pdf_capacity.locked()
    finally:
        await release


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


def _hung_supervisor(path):
    with (
        patch.object(TextExtractor, "_extract_pdf_in_child", _hanging_child),
        patch(
            "eneo.files.text.TemporaryDirectory",
            partial(TemporaryDirectory, dir=path.parent),
        ),
    ):
        asyncio.run(TextExtractor.extract_from_pdf_async(path, limits=_LIMITS))


def test_pdf_child_deadline_survives_killed_supervisor(tmp_path):
    path = _write_pdf(tmp_path / "orphan.pdf", 1)
    pid_path = path.with_suffix(".pid")
    supervisor = multiprocessing.get_context("spawn").Process(
        target=_hung_supervisor, args=(path,)
    )
    child_pid = None
    try:
        supervisor.start()
        deadline = time.monotonic() + 2
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_path.exists(), "parser did not start"
        child_pid = int(pid_path.read_text())
        supervisor.kill()
        supervisor.join(1)
        assert not supervisor.is_alive()

        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            pytest.fail("PDF parser survived its deadline after supervisor death")
    finally:
        if supervisor.is_alive():
            supervisor.kill()
            supervisor.join()
        supervisor.close()
        if child_pid is not None:
            with suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_pdf_page_limit_refuses_before_reading_any_page(tmp_path):
    path = _write_pdf(tmp_path / "many.pdf", 3)

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        await _ObservedExtractor.extract_from_pdf_async(
            path, limits=replace(_LIMITS, max_pages=2)
        )

    assert (caught.value.limit, caught.value.measured, caught.value.ceiling) == (
        "pages",
        3,
        2,
    )
    assert not path.with_suffix(".pages").exists()


@pytest.mark.asyncio
async def test_pdf_byte_limit_includes_utf8_markers_and_page_separators(tmp_path):
    path = _write_pdf(tmp_path / "many.pdf", 3)

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        await _ObservedExtractor.extract_from_pdf_async(
            path, limits=replace(_LIMITS, max_extracted_bytes=23)
        )

    assert (caught.value.limit, caught.value.measured, caught.value.ceiling) == (
        "extracted_bytes",
        24,
        23,
    )
    assert path.with_suffix(".pages").read_text() == "1\n2\n"


@pytest.mark.asyncio
async def test_pdf_at_page_and_byte_limits_is_accepted(tmp_path):
    path = _write_pdf(tmp_path / "exact.pdf", 2)

    assert (
        await _ObservedExtractor.extract_from_pdf_async(
            path, limits=replace(_LIMITS, max_pages=2, max_extracted_bytes=24)
        )
        == "[PAGE 1]\nå\n\n[PAGE 2]\nå"
    )


@pytest.mark.asyncio
async def test_hanging_pdf_parser_is_killed_and_reaped(tmp_path, monkeypatch):
    monkeypatch.setattr(
        TextExtractor, "_extract_pdf_in_child", staticmethod(_hanging_child)
    )
    path = _write_pdf(tmp_path / "hang.pdf", 1)
    started = time.monotonic()

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        await TextExtractor.extract_from_pdf_async(path, limits=_LIMITS)

    elapsed = time.monotonic() - started
    assert caught.value.limit == "seconds"
    assert caught.value.ceiling == 2
    assert 2 <= caught.value.measured <= elapsed < 3.5
    pid = int(path.with_suffix(".pid").read_text())
    assert all(child.pid != pid for child in multiprocessing.active_children())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_pdf_refusal_bypasses_plain_text_fallback(tmp_path):
    path = _write_pdf(tmp_path / "refusal.pdf", 1)

    with pytest.raises(PdfExtractionLimitExceeded) as caught:
        await _RefusingExtractor.extract_from_pdf_async(path, limits=_LIMITS)

    assert (caught.value.limit, caught.value.measured, caught.value.ceiling) == (
        "extracted_bytes",
        11,
        10,
    )


@pytest.mark.asyncio
async def test_pdf_child_crash_is_an_extraction_error_and_is_reaped(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        TextExtractor, "_extract_pdf_in_child", staticmethod(_crashed_child)
    )
    path = _write_pdf(tmp_path / "crash.pdf", 1)

    with pytest.raises(ExtractionError, match="exited with code 17"):
        await TextExtractor.extract_from_pdf_async(path, limits=_LIMITS)

    pid = int(path.with_suffix(".pid").read_text())
    assert all(child.pid != pid for child in multiprocessing.active_children())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("bounded", [False, True])
async def test_pdf_fixture_preserves_golden_text(bounded):
    fixture = (
        Path(__file__).resolve().parents[3]
        / "scripts/fixtures/ai_builder_battle/06_tidigare_beslut.pdf"
    )
    result = (
        await TextExtractor.extract_from_pdf_async(fixture, limits=_LIMITS)
        if bounded
        else TextExtractor.extract_from_pdf(fixture)
    )
    assert result == (
        "[PAGE 1]\nProtokollsutdrag - Barn- och utbildningsnamndens arbetsutskott\n"
        "Diarienummer: BUN-2026-00037-1\nSammantradesdatum: 2026-02-11\n"
        "Paragraf 11: Ny forskolestruktur i Njurunda\n"
        "Arbetsutskottet foreslar avveckling av Klockarbergets forskola.\n"
        "Forslaget motiveras av minskat barnantal i Njurunda.\n"
        "Beslutet ska forenas med trygg overgangen for barn och personal.\n"
        "Personaltatheten ska i genomsnitt vara hogst 5,0 barn per anstalld.\n"
        "Arkiveringsstampel:\nB\nE\nS\nL\nU\nT\nA\nD"
    )
