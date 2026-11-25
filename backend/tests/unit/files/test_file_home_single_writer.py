"""``files.home_space_id`` has one writer.

Code that creates or attaches a File passes its context to
``eneo.files.file_home`` and never writes the column itself: the home is
shared by a File's family and kept for good, and a second writer would be a
second place to get that wrong.
"""

import re
from pathlib import Path

import eneo

# Assigning the column: a keyword argument or an attribute assignment, not a
# comparison such as ``Files.home_space_id == space_id``.
_WRITES_THE_HOME = re.compile(r"home_space_id\s*=(?!=)")
_MAY_WRITE = {
    # Declares the column.
    Path("database/tables/files_table.py"),
    # Owns it.
    Path("files/file_home.py"),
}


def test_only_the_file_home_module_writes_a_files_home() -> None:
    source_root = Path(eneo.__file__).parent
    writers = sorted(
        str(path.relative_to(source_root))
        for path in source_root.rglob("*.py")
        if path.relative_to(source_root) not in _MAY_WRITE
        and _WRITES_THE_HOME.search(path.read_text(encoding="utf-8"))
    )

    assert writers == []
