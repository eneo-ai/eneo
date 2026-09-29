"""Which repository code is running, and whether it is one tree's.

A measurement names a commit and a clean tree (`git rev-parse HEAD`, `git status`
in the working directory), but Python imports the code from wherever `sys.path`
points: a `PYTHONPATH` or an editable install can load `eneo` from one checkout
while the working directory, the freeze's `--tree` or the recorded revision is
another. Their bytes may even be equal for the scripts and differ in a module
nobody compared (the question catalog an author is shown answers from).

The plain guard is by PATH IDENTITY, not by bytes: every loaded module of the
repository's code must live inside the tree that is being measured. Repository
code is identified by NAME as well as by path, because a copy preloaded from
elsewhere (a site-packages install of `ai_builder_intake_answers`) is imported by
module name and sits at a path that says nothing: an `eneo` module; a module
whose name is a first-party script of the target tree (a `.py` file, or a package,
in its `backend/scripts`, derived by listing that directory); and any module
whose file sits under a `backend/src` or a `backend/scripts` directory. A leaf:
standard library only.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

CODE_ROOTS = ("src", "scripts")


class CodeIdentityError(ValueError):
    """Code that is not the measured tree's is loaded."""


def code_root_of(path: Path) -> str | None:
    """`src` or `scripts` when `path` sits under a `backend/src` or a
    `backend/scripts` directory, else None."""

    parts = path.parts
    for index in range(len(parts) - 2):
        if parts[index] == "backend" and parts[index + 1] in CODE_ROOTS:
            return parts[index + 1]
    return None


def first_party_names(tree: Path) -> frozenset[str]:
    """The module names `tree`'s `backend/scripts` provides: every `.py` file, and
    every package (a directory with an `__init__.py`). Derived by listing, so a
    script added tomorrow is covered without anyone updating a list."""

    scripts = tree / "backend" / "scripts"
    names: set[str] = set()
    if scripts.is_dir():
        for entry in scripts.iterdir():
            if entry.is_file() and entry.suffix == ".py":
                names.add(entry.stem)
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                names.add(entry.name)
    return frozenset(names)


def loaded_code() -> list[tuple[str, Path]]:
    """(module name, real path) of every loaded module that has a file. Which of
    them are the repository's is `code_outside_tree`'s question, by name and by
    path."""

    found: list[tuple[str, Path]] = []
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if isinstance(file, str):
            found.append((name, Path(file).resolve()))
    return found


def code_outside_tree(
    tree: Path, loaded: Iterable[tuple[str, Path]] | None = None
) -> list[tuple[str, Path]]:
    """The loaded repository modules that are not inside `tree`.

    A module is the repository's when it is an `eneo` module (which must lie in
    `tree/backend/src`, a site-packages copy is foreign too), when its top-level
    name is one `tree/backend/scripts` provides (which must lie in
    `tree/backend/scripts`, wherever else a module of that name was found), or
    when its file sits under some `backend/src` or `backend/scripts` directory
    (which must be `tree`'s).
    """

    allowed = {
        "src": (tree / "backend" / "src").resolve(),
        "scripts": (tree / "backend" / "scripts").resolve(),
    }
    first_party = first_party_names(tree)
    outside: list[tuple[str, Path]] = []
    for name, real in loaded if loaded is not None else loaded_code():
        if name == "eneo" or name.startswith("eneo."):
            root: str | None = "src"
        elif name.split(".")[0] in first_party:
            root = "scripts"
        else:
            root = code_root_of(real)
        if root is not None and not real.is_relative_to(allowed[root]):
            outside.append((name, real))
    return sorted(outside, key=lambda item: str(item[1]))


def require_code_from_tree(tree: Path, *, what: str) -> None:
    """Refuse unless every loaded repository module is inside `tree`.

    `what` says what is being measured (a freeze, a leg) for the message. The
    first foreign module paths are named, so the operator can see which checkout
    the code came from.
    """

    outside = code_outside_tree(tree)
    if outside:
        shown = "; ".join(f"{name} from {path}" for name, path in outside[:5])
        more = f" and {len(outside) - 5} more" if len(outside) > 5 else ""
        raise CodeIdentityError(
            f"{what} must run the code of the tree it measures ({tree}), but code "
            f"from another checkout or install is loaded: {shown}{more}. Run it "
            f"from that tree, with PYTHONPATH={tree}/backend/src."
        )
