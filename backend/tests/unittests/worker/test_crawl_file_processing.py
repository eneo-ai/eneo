import ast
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

import intric.worker.crawl.file_processing as file_processing
from intric.worker.crawl.file_processing import FileProcessingResult, process_files
from intric.worker.crawl.persistence import ExistingBlobState


async def _process_changed_file_never_called(
    *_args: object,
) -> None:
    raise AssertionError("process_changed_file should not be called")


def _file_hash(path: Path) -> bytes:
    return hashlib.sha256(path.read_bytes()).digest()


@pytest.mark.asyncio
async def test_process_files_accepts_empty_or_missing_file_iterables() -> None:
    result = await process_files(
        files=None,
        existing_blob_state_by_title={},
        embedding_model_id=None,
        process_changed_file=_process_changed_file_never_called,
    )

    assert isinstance(result, FileProcessingResult)
    assert result.files_downloaded == 0
    assert result.files_hash_retained == 0
    assert result.files_failed == 0
    assert result.cleanup_protected_titles == frozenset()
    assert result.failed_titles == frozenset()


@pytest.mark.asyncio
async def test_process_files_retains_unchanged_file_without_callback(
    tmp_path: Path,
) -> None:
    embedding_model_id = uuid4()
    file = tmp_path / "policy.pdf"
    file.write_bytes(b"stable file bytes")

    result = await process_files(
        files=[file],
        existing_blob_state_by_title={
            "policy": ExistingBlobState(
                content_hash=_file_hash(file),
                embedding_model_id=embedding_model_id,
            )
        },
        embedding_model_id=embedding_model_id,
        process_changed_file=_process_changed_file_never_called,
    )

    assert result.files_downloaded == 1
    assert result.files_hash_retained == 1
    assert result.files_failed == 0
    assert result.cleanup_protected_titles == frozenset({"policy"})
    assert result.failed_titles == frozenset()


@pytest.mark.asyncio
async def test_process_files_processes_changed_file_with_hash(
    tmp_path: Path,
) -> None:
    processed: list[tuple[Path, str, bytes]] = []
    file = tmp_path / "agenda.pdf"
    file.write_bytes(b"new file bytes")

    async def process_changed_file(
        path: Path,
        filename: str,
        content_hash: bytes,
    ) -> None:
        processed.append((path, filename, content_hash))

    result = await process_files(
        files=[file],
        existing_blob_state_by_title={},
        embedding_model_id=uuid4(),
        process_changed_file=process_changed_file,
    )

    assert processed == [(file, "agenda", _file_hash(file))]
    assert result.files_downloaded == 1
    assert result.files_hash_retained == 0
    assert result.files_failed == 0
    assert result.cleanup_protected_titles == frozenset({"agenda"})
    assert result.failed_titles == frozenset()


@pytest.mark.asyncio
async def test_process_files_continues_after_callback_failure(
    tmp_path: Path,
) -> None:
    processed_filenames: list[str] = []
    recorded_errors: list[tuple[Path, str, BaseException]] = []
    failed_file = tmp_path / "broken.pdf"
    successful_file = tmp_path / "ok.pdf"
    failed_file.write_bytes(b"broken")
    successful_file.write_bytes(b"ok")

    async def process_changed_file(
        _path: Path,
        filename: str,
        _content_hash: bytes,
    ) -> None:
        if filename == "broken":
            raise ValueError("parser failed")
        processed_filenames.append(filename)

    def record_file_processing_error(
        path: Path,
        filename: str,
        exc: BaseException,
    ) -> None:
        recorded_errors.append((path, filename, exc))

    result = await process_files(
        files=[failed_file, successful_file],
        existing_blob_state_by_title={},
        embedding_model_id=uuid4(),
        process_changed_file=process_changed_file,
        record_file_processing_error=record_file_processing_error,
    )

    assert processed_filenames == ["ok"]
    assert result.files_downloaded == 2
    assert result.files_hash_retained == 0
    assert result.files_failed == 1
    assert result.cleanup_protected_titles == frozenset({"ok"})
    assert result.failed_titles == frozenset({"broken"})
    assert recorded_errors[0][0] == failed_file
    assert recorded_errors[0][1] == "broken"
    assert isinstance(recorded_errors[0][2], ValueError)


@pytest.mark.asyncio
async def test_process_files_continues_after_file_read_failure(
    tmp_path: Path,
) -> None:
    processed_filenames: list[str] = []
    recorded_errors: list[tuple[Path, str, BaseException]] = []
    missing_file = tmp_path / "missing.pdf"
    successful_file = tmp_path / "ok.pdf"
    successful_file.write_bytes(b"ok")

    async def process_changed_file(
        _path: Path,
        filename: str,
        _content_hash: bytes,
    ) -> None:
        processed_filenames.append(filename)

    def record_file_processing_error(
        path: Path,
        filename: str,
        exc: BaseException,
    ) -> None:
        recorded_errors.append((path, filename, exc))

    result = await process_files(
        files=[missing_file, successful_file],
        existing_blob_state_by_title={},
        embedding_model_id=uuid4(),
        process_changed_file=process_changed_file,
        record_file_processing_error=record_file_processing_error,
    )

    assert processed_filenames == ["ok"]
    assert result.files_downloaded == 2
    assert result.files_hash_retained == 0
    assert result.files_failed == 1
    assert result.cleanup_protected_titles == frozenset({"ok"})
    assert result.failed_titles == frozenset({"missing"})
    assert recorded_errors[0][0] == missing_file
    assert recorded_errors[0][1] == "missing"
    assert isinstance(recorded_errors[0][2], FileNotFoundError)


@pytest.mark.asyncio
async def test_process_files_tracks_retained_processed_and_failed_files_together(
    tmp_path: Path,
) -> None:
    embedding_model_id = uuid4()
    processed_filenames: list[str] = []
    retained_file = tmp_path / "retained.pdf"
    processed_file = tmp_path / "processed.pdf"
    failed_file = tmp_path / "failed.pdf"
    retained_file.write_bytes(b"retained")
    processed_file.write_bytes(b"processed")
    failed_file.write_bytes(b"failed")

    async def process_changed_file(
        _path: Path,
        filename: str,
        _content_hash: bytes,
    ) -> None:
        if filename == "failed":
            raise ValueError("parser failed")
        processed_filenames.append(filename)

    result = await process_files(
        files=[retained_file, processed_file, failed_file],
        existing_blob_state_by_title={
            "retained": ExistingBlobState(
                content_hash=_file_hash(retained_file),
                embedding_model_id=embedding_model_id,
            )
        },
        embedding_model_id=embedding_model_id,
        process_changed_file=process_changed_file,
    )

    assert processed_filenames == ["processed"]
    assert result.files_downloaded == 3
    assert result.files_hash_retained == 1
    assert result.files_failed == 1
    assert result.cleanup_protected_titles == frozenset({"retained", "processed"})
    assert result.failed_titles == frozenset({"failed"})


@pytest.mark.asyncio
async def test_process_files_reprocesses_same_content_for_changed_embedding_model(
    tmp_path: Path,
) -> None:
    processed_filenames: list[str] = []
    current_embedding_model_id = uuid4()
    file = tmp_path / "contract.pdf"
    file.write_bytes(b"same content")

    async def process_changed_file(
        _path: Path,
        filename: str,
        _content_hash: bytes,
    ) -> None:
        processed_filenames.append(filename)

    result = await process_files(
        files=[file],
        existing_blob_state_by_title={
            "contract": ExistingBlobState(
                content_hash=_file_hash(file),
                embedding_model_id=uuid4(),
            )
        },
        embedding_model_id=current_embedding_model_id,
        process_changed_file=process_changed_file,
    )

    assert processed_filenames == ["contract"]
    assert result.files_downloaded == 1
    assert result.files_hash_retained == 0
    assert result.files_failed == 0
    assert result.cleanup_protected_titles == frozenset({"contract"})
    assert result.failed_titles == frozenset()


@pytest.mark.asyncio
async def test_process_files_missing_embedding_model_retains_only_unchanged_files(
    tmp_path: Path,
) -> None:
    recorded_errors: list[tuple[Path, str, Exception]] = []
    retained_file = tmp_path / "unchanged.pdf"
    changed_file = tmp_path / "changed.pdf"
    retained_file.write_bytes(b"stable")
    changed_file.write_bytes(b"changed")

    def record_file_processing_error(
        path: Path,
        filename: str,
        exc: Exception,
    ) -> None:
        recorded_errors.append((path, filename, exc))

    result = await process_files(
        files=[retained_file, changed_file],
        existing_blob_state_by_title={
            "unchanged": ExistingBlobState(
                content_hash=_file_hash(retained_file),
                embedding_model_id=uuid4(),
            )
        },
        embedding_model_id=None,
        process_changed_file=_process_changed_file_never_called,
        record_file_processing_error=record_file_processing_error,
    )

    assert result.files_downloaded == 2
    assert result.files_hash_retained == 1
    assert result.files_failed == 1
    assert result.cleanup_protected_titles == frozenset({"unchanged"})
    assert result.failed_titles == frozenset({"changed"})
    assert recorded_errors[0][0] == changed_file
    assert recorded_errors[0][1] == "changed"
    assert isinstance(
        recorded_errors[0][2], file_processing.MissingFileEmbeddingModelError
    )


def test_file_processing_phase_has_no_runtime_or_infrastructure_imports() -> None:
    assert file_processing.__file__ is not None
    source = Path(file_processing.__file__).read_text()
    tree = ast.parse(source)
    forbidden_module_prefixes = (
        "arq",
        "dependency_injector",
        "intric.crawler",
        "intric.main.container",
        "intric.worker.crawl.recovery",
        "intric.worker.crawl.terminal",
        "scrapy",
        "sqlalchemy",
    )
    forbidden_names = {
        "AsyncSession",
        "Container",
        "HeartbeatMonitor",
        "SessionHolder",
        "TerminalEvent",
        "execute_with_recovery",
        "providers",
    }
    imported_modules: set[str] = set()
    imported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                imported_names.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imported_modules.add(node.module)
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)

    assert not any(
        module == prefix or module.startswith(f"{prefix}.")
        for module in imported_modules
        for prefix in forbidden_module_prefixes
    )
    assert not forbidden_names.intersection(imported_names)
