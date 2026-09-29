"""Which repository code is loaded, and whether it is one tree's, by path."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_builder_code_identity as identity  # noqa: E402


def _tree(tmp_path: Path, name: str) -> Path:
    tree = tmp_path / name
    (tree / "backend" / "src" / "eneo").mkdir(parents=True)
    (tree / "backend" / "scripts").mkdir(parents=True)
    return tree


def test_repository_code_is_told_from_the_directory_it_sits_in(tmp_path: Path) -> None:
    tree = _tree(tmp_path, "t")

    assert identity.code_root_of(tree / "backend/src/eneo/a.py") == "src"
    assert identity.code_root_of(tree / "backend/scripts/x.py") == "scripts"
    assert identity.code_root_of(tree / "backend/tests/x.py") is None
    assert identity.code_root_of(tmp_path / "site-packages/eneo/a.py") is None


def test_every_module_inside_the_tree_is_accepted_and_others_are_named(
    tmp_path: Path,
) -> None:
    ours, theirs = _tree(tmp_path, "ours"), _tree(tmp_path, "theirs")
    loaded = [
        ("eneo.flows.a", ours / "backend/src/eneo/flows/a.py"),
        ("ai_builder_receipt", ours / "backend/scripts/ai_builder_receipt.py"),
        ("__main__", ours / "backend/scripts/ai_builder_oracle_totals.py"),
    ]
    assert identity.code_outside_tree(ours, loaded) == []

    loaded += [
        (
            "eneo.flows.ai_builder.question_catalog",
            theirs / "backend/src/eneo/flows/q.py",
        ),
        (
            "ai_builder_intake_answers",
            theirs / "backend/scripts/ai_builder_intake_answers.py",
        ),
    ]
    outside = identity.code_outside_tree(ours, loaded)
    assert {name for name, _ in outside} == {
        "eneo.flows.ai_builder.question_catalog",
        "ai_builder_intake_answers",
    }
    assert all(path.is_relative_to(theirs) for _, path in outside)


def test_an_eneo_module_outside_any_backend_src_is_foreign_too(tmp_path: Path) -> None:
    """An installed copy (site-packages) is `eneo` code from another place."""

    ours = _tree(tmp_path, "ours")
    installed = tmp_path / "site-packages" / "eneo" / "flows" / "a.py"

    outside = identity.code_outside_tree(ours, [("eneo.flows.a", installed)])

    assert outside == [("eneo.flows.a", installed)]
    # A dependency that is not the repository's is not this guard's business.
    assert (
        identity.code_outside_tree(
            ours, [("pytest", tmp_path / "site-packages/pytest.py")]
        )
        == []
    )


def test_a_symlinked_checkout_is_the_same_tree(tmp_path: Path) -> None:
    real = _tree(tmp_path, "real")
    module = real / "backend/src/eneo/a.py"
    module.write_text("")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    # The loaded path is resolved; the tree asked about may be given either way.
    resolved = module.resolve()
    assert identity.code_outside_tree(link, [("eneo.a", resolved)]) == []
    assert identity.code_outside_tree(real, [("eneo.a", resolved)]) == []


def test_the_processs_own_code_is_found_and_belongs_to_this_checkout(
    tmp_path: Path,
) -> None:
    checkout = Path(__file__).resolve().parents[5]

    loaded = dict(identity.loaded_code())

    assert loaded["ai_builder_code_identity"] == (
        checkout / "backend/scripts/ai_builder_code_identity.py"
    )
    assert any(name.startswith("eneo.") for name in loaded)
    assert identity.code_outside_tree(checkout) == []  # all of it, from one place
    foreign = identity.code_outside_tree(tmp_path)
    assert foreign and all(path.is_relative_to(checkout) for _, path in foreign)
    with pytest.raises(identity.CodeIdentityError, match="another checkout"):
        identity.require_code_from_tree(tmp_path, what="A leg")


def test_a_first_party_script_preloaded_from_elsewhere_is_foreign_by_name(
    tmp_path: Path,
) -> None:
    """Commit gate round 6: a copy of a script preloaded from a site-packages-like
    path is imported by module NAME and its path says nothing about a repository,
    so it is classified by the names the target tree's `backend/scripts` provides."""

    ours = _tree(tmp_path, "ours")
    scripts = ours / "backend" / "scripts"
    for name in ("ai_builder_intake_answers", "ai_builder_oracle_arm"):
        (scripts / f"{name}.py").write_text("")
    (scripts / "pkg").mkdir()
    (scripts / "pkg" / "__init__.py").write_text("")
    (scripts / "fixtures").mkdir()  # a directory that is not a package
    site = tmp_path / "site-packages"
    loaded = [
        ("ai_builder_intake_answers", site / "ai_builder_intake_answers.py"),
        ("ai_builder_oracle_arm", site / "ai_builder_oracle_arm.py"),
        ("pkg.sub", site / "pkg" / "sub.py"),
        ("fixtures", site / "fixtures" / "__init__.py"),  # not first party
        ("yaml", site / "yaml" / "__init__.py"),  # a dependency
        ("ai_builder_intake_answers", scripts / "ai_builder_intake_answers.py"),
    ]

    outside = identity.code_outside_tree(ours, loaded)

    assert identity.first_party_names(ours) == {
        "ai_builder_intake_answers",
        "ai_builder_oracle_arm",
        "pkg",
    }
    assert sorted(name for name, _ in outside) == [
        "ai_builder_intake_answers",
        "ai_builder_oracle_arm",
        "pkg.sub",
    ]
    assert all(path.is_relative_to(site) for _, path in outside)


def test_preloaded_foreign_scripts_are_refused_in_the_real_process_and_the_real_tree_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = Path(__file__).resolve().parents[5]
    identity.require_code_from_tree(checkout, what="A leg")  # the real tree passes

    site = tmp_path / "site-packages"
    site.mkdir()
    for name in ("ai_builder_intake_answers", "ai_builder_oracle_arm"):
        fake = ModuleType(name)
        fake.__file__ = str(site / f"{name}.py")
        monkeypatch.setitem(sys.modules, name, fake)

    with pytest.raises(identity.CodeIdentityError) as info:
        identity.require_code_from_tree(checkout, what="A leg")

    assert str(site / "ai_builder_intake_answers.py") in str(info.value)
    assert str(site / "ai_builder_oracle_arm.py") in str(info.value)
