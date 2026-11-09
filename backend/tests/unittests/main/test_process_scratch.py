"""Each process keeps its temporary files in its own directory under
upload_tmp_dir, removed after use; a crashed process's directory is reclaimed
only once its owner is gone, and nothing else in upload_tmp_dir is touched."""

import ast
import fcntl
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from eneo.main import process_scratch

_SOURCE = Path(process_scratch.__file__).parents[1]
_NAMED_TEMPORARY = {"NamedTemporaryFile", "TemporaryDirectory", "mkdtemp", "mkstemp"}


@pytest.fixture
def upload_tmp_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    settings = SimpleNamespace(upload_tmp_dir=tmp_path)
    monkeypatch.setattr(process_scratch, "get_settings", lambda: settings)
    yield tmp_path
    process_scratch.stop()


def _crashed(root: Path, name: str, *, age_seconds: float = 0) -> Path:
    """A directory as a process that died left it: marker unlocked."""
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "owner.lock").touch()
    (directory / "removed-content.wav").write_bytes(b"bytes of a removed turn")
    if age_seconds:
        then = time.time() - age_seconds
        os.utime(directory, (then, then))
    return directory


def test_a_process_writes_into_its_own_directory(upload_tmp_dir: Path) -> None:
    directory = process_scratch.start()

    assert directory.parent == upload_tmp_dir / "eneo-scratch"
    assert directory.name.startswith("proc-")
    assert process_scratch.directory() == directory


def test_stop_removes_the_directory_with_its_files(upload_tmp_dir: Path) -> None:
    directory = process_scratch.start()
    (directory / "upload").write_bytes(b"content")

    process_scratch.stop()

    assert not directory.exists()


def test_start_never_empties_upload_tmp_dir(upload_tmp_dir: Path) -> None:
    staged = upload_tmp_dir / "job-staging" / "a-job"
    staged.mkdir(parents=True)
    loose = upload_tmp_dir / "someone-elses-file"
    loose.write_bytes(b"kept")

    process_scratch.start()

    assert staged.exists()
    assert loose.read_bytes() == b"kept"


def test_a_directory_whose_owner_is_gone_is_reclaimed(upload_tmp_dir: Path) -> None:
    orphan = _crashed(upload_tmp_dir / "eneo-scratch", "proc-crashed")

    process_scratch.start()

    assert not orphan.exists()


def test_a_directory_whose_owner_lives_is_kept(upload_tmp_dir: Path) -> None:
    live = _crashed(upload_tmp_dir / "eneo-scratch", "proc-live")
    with (live / "owner.lock").open("rb") as marker:
        # flock belongs to the open file, so this descriptor stands in for
        # another live process holding its own directory.
        fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)

        process_scratch.start()

        assert live.exists()


def test_a_directory_being_created_is_kept_until_it_is_old(
    upload_tmp_dir: Path,
) -> None:
    root = upload_tmp_dir / "eneo-scratch"
    creating = _crashed(root, ".new-fresh")
    abandoned = _crashed(root, ".new-abandoned", age_seconds=2 * 3600)
    unmarked = root / "proc-unmarked"
    unmarked.mkdir()
    old = time.time() - 2 * 3600
    os.utime(unmarked, (old, old))

    process_scratch.start()

    assert creating.exists()
    assert not abandoned.exists()
    assert not unmarked.exists()


def test_reclaiming_is_bounded_and_continues_on_the_next_start(
    upload_tmp_dir: Path,
) -> None:
    root = upload_tmp_dir / "eneo-scratch"
    for index in range(process_scratch.RECLAIM_LIMIT + 10):
        _crashed(root, f"proc-{index:04d}")

    assert process_scratch.reclaim(root) == process_scratch.RECLAIM_LIMIT
    assert process_scratch.reclaim(root) == 10


def test_live_directories_do_not_hide_orphans_behind_them(
    upload_tmp_dir: Path,
) -> None:
    root = upload_tmp_dir / "eneo-scratch"
    markers = []
    for index in range(process_scratch.RECLAIM_LIMIT + 5):
        live = _crashed(root, f"proc-a{index:04d}")
        marker = (live / "owner.lock").open("rb")
        fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        markers.append(marker)
    orphan = _crashed(root, "proc-z-crashed")
    try:
        assert process_scratch.reclaim(root) == 1
        assert not orphan.exists()
    finally:
        for marker in markers:
            marker.close()


def test_a_crashed_parent_is_reclaimed_while_its_forked_child_lives(
    upload_tmp_dir: Path,
) -> None:
    """A forked child writes into its own directory and closes its copy of the
    parent's lock, so the parent's directory goes once the parent dies."""
    paths_read, paths_written = os.pipe()
    release_read, release_written = os.pipe()
    parent = os.fork()
    if parent == 0:  # pragma: no cover - the crashing parent process
        try:
            os.close(paths_read)
            os.close(release_written)
            parent_directory = process_scratch.start()
            if os.fork() == 0:  # the child that outlives it
                own = process_scratch.directory()
                os.write(paths_written, f"{parent_directory}\n{own}\n".encode())
                os.read(release_read, 1)
        finally:
            # Ends without stop() or exit handlers: a crash.
            os._exit(0)
    os.close(paths_written)
    os.close(release_read)
    try:
        written = b""
        while written.count(b"\n") < 2:
            chunk = os.read(paths_read, 4096)
            assert chunk, "the forked child never reported its directory"
            written += chunk
        parent_directory, child_directory = (
            Path(line) for line in written.decode().split()
        )
        os.waitpid(parent, 0)

        assert child_directory != parent_directory
        assert process_scratch.reclaim(upload_tmp_dir / "eneo-scratch") == 1
        assert not parent_directory.exists()
        assert child_directory.exists()
    finally:
        os.close(release_written)
        os.close(paths_read)


def _refuse(monkeypatch: pytest.MonkeyPatch, refused: Path) -> None:
    remove_tree = process_scratch.shutil.rmtree

    def rmtree(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path) == refused:
            raise PermissionError(13, "Permission denied")
        remove_tree(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(process_scratch.shutil, "rmtree", rmtree)


def test_a_directory_that_cannot_be_removed_is_not_counted_and_is_kept(
    upload_tmp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mutant: a failed removal counts as one and nothing says why."""
    root = upload_tmp_dir / "eneo-scratch"
    refused = _crashed(root, "proc-refused")
    removable = _crashed(root, "proc-removable")
    _refuse(monkeypatch, refused)

    with caplog.at_level(logging.WARNING, logger=process_scratch.logger.name):
        removed = process_scratch.reclaim(root)

    assert removed == 1
    assert refused.is_dir()
    assert not removable.exists()
    [record] = caplog.records
    assert getattr(record, "directory") == "proc-refused"
    assert "removed-content" not in caplog.text


def test_a_directory_stop_cannot_remove_is_left_for_a_later_start(
    upload_tmp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    directory = process_scratch.start()
    (directory / "upload").write_bytes(b"content")
    _refuse(monkeypatch, directory)

    with caplog.at_level(logging.WARNING, logger=process_scratch.logger.name):
        process_scratch.stop()

    assert directory.is_dir()
    assert len(caplog.records) == 1
    monkeypatch.undo()
    monkeypatch.setattr(
        process_scratch,
        "get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=upload_tmp_dir),
    )
    assert process_scratch.reclaim(directory.parent) == 1
    assert not directory.exists()


def test_every_named_temporary_file_is_made_in_process_scratch() -> None:
    """A temporary file with a name outlives a crash; only process scratch
    reclaims it, so every one is made there (`dir=`)."""
    unscoped = []
    for path in _SOURCE.rglob("*.py"):
        if path == Path(process_scratch.__file__):
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", None))
            if name in _NAMED_TEMPORARY and not any(
                keyword.arg == "dir" for keyword in node.keywords
            ):
                unscoped.append(f"{path.relative_to(_SOURCE)}:{node.lineno}")

    assert unscoped == []
