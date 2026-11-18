"""Named temporary files of this process, in a directory of its own.

Every named temporary file the backend writes (an upload before it is stored,
audio being transcribed, crawled files, extracted archives) goes into
`upload_tmp_dir/eneo-scratch/proc-<random>/`. The process holds an exclusive
lock on that directory's `owner.lock` while it lives and removes the
directory when it stops. A process that crashes leaves its directory behind;
a later start removes it once its lock can be taken, which the kernel allows
only after every holder is gone. Nothing else in `upload_tmp_dir` is touched:
job staging keeps its own lifecycle.

A forked child does not use or keep its parent's directory: it closes its copy
of the lock (without unlocking it) and makes its own on first use.

The lock is a `flock` on a local filesystem. A directory shared between
hosts over a network filesystem is not supported.
"""

from __future__ import annotations

import atexit
import contextlib
import fcntl
import logging
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from eneo.main.config import get_settings

logger = logging.getLogger(__name__)
_SCRATCH = "eneo-scratch"
_MARKER = "owner.lock"
_LIVE = "proc-"
_NEW = ".new-"
# ponytail: removes this many abandoned directories per start; later starts take the rest.
RECLAIM_LIMIT = 64
# A directory without its marker, or still being created, is removed only
# once no process can still be creating it.
_CREATION_GRACE_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class _Owned:
    pid: int
    path: Path
    marker: int


_owned: _Owned | None = None
_making = threading.Lock()


def _root() -> Path:
    return Path(get_settings().upload_tmp_dir) / _SCRATCH


def start() -> Path:
    """Remove directories whose owners are gone, then make this process's."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    reclaim(root)
    return directory()


def directory() -> Path:
    """This process's directory, made on first use."""
    global _owned
    with _making:
        if _owned is not None and _owned.pid == os.getpid():
            return _owned.path
        _owned = _make()
        return _owned.path


def _make() -> _Owned:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    # Locked before it gets the name a reclaim looks for.
    creating = Path(tempfile.mkdtemp(prefix=_NEW, dir=root))
    marker = os.open(creating / _MARKER, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    fcntl.flock(marker, fcntl.LOCK_EX)
    path = root / f"{_LIVE}{creating.name.removeprefix(_NEW)}"
    creating.rename(path)
    return _Owned(pid=os.getpid(), path=path, marker=marker)


def stop() -> None:
    """Remove this process's directory and everything in it."""
    global _owned
    owned, _owned = _owned, None
    if owned is None or owned.pid != os.getpid():
        return
    # A directory left behind is unlocked once the marker closes, so a later
    # start reclaims it.
    _remove(owned.path)
    os.close(owned.marker)


def reclaim(root: Path) -> int:
    """Remove up to RECLAIM_LIMIT directories whose owners are gone.

    Every entry is looked at, so live directories never hide abandoned ones
    behind them; only removals are bounded."""
    try:
        entries = list(os.scandir(root))
    except FileNotFoundError:
        return 0
    removed = 0
    for entry in entries:
        if removed == RECLAIM_LIMIT:
            break
        if not entry.is_dir(follow_symlinks=False):
            continue
        path = Path(entry.path)
        if entry.name.startswith(_LIVE):
            removed += _remove_if_abandoned(path)
        elif entry.name.startswith(_NEW):
            removed += _remove_if_old(path)
    return removed


def _remove_if_abandoned(path: Path) -> int:
    try:
        marker = os.open(path / _MARKER, os.O_RDWR | os.O_CLOEXEC)
    except FileNotFoundError:
        return _remove_if_old(path)
    try:
        try:
            fcntl.flock(marker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        # Removed while locked, so no process can take the directory meanwhile.
        return _remove(path)
    finally:
        os.close(marker)


def _remove_if_old(path: Path) -> int:
    with contextlib.suppress(FileNotFoundError):
        if time.time() - path.stat().st_mtime > _CREATION_GRACE_SECONDS:
            return _remove(path)
    return 0


def _remove(path: Path) -> int:
    """1 once the directory is gone. One that cannot be removed is kept for a
    later start, and the log names it without its content."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return 0
    except OSError as error:
        logger.warning(
            "Scratch directory could not be removed",
            extra={"directory": path.name, "errno": error.errno},
        )
        return 0
    return 1


def _forget_inherited() -> None:
    """In a forked child: close its copy of the parent's lock. Closing does not
    unlock it, and the parent's directory goes with the parent alone."""
    global _owned
    if _owned is not None:
        with contextlib.suppress(OSError):
            os.close(_owned.marker)
        _owned = None


os.register_at_fork(after_in_child=_forget_inherited)
atexit.register(stop)
