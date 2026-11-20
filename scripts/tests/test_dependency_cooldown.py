"""Every package resolver waits the same time for a new release, without whole-package exceptions."""

from __future__ import annotations

import re
import subprocess
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUN_CONFIGS = ("frontend/bunfig.toml", "tool-runtime/bunfig.toml")
UV_CONFIGS = ("backend/pyproject.toml", "tool-runtime/uv.toml")

EXACT_RELEASE = re.compile(r"^(@[^/@\s]+/)?[^/@\s]+@\d+\.\d+\.\d+\S*$")
UPLOAD_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def bun_install(text: str) -> dict:
    return tomllib.loads(text).get("install", {})


def uv_settings(text: str, *, pyproject: bool) -> dict:
    document = tomllib.loads(text)
    return document.get("tool", {}).get("uv", {}) if pyproject else document


def read_uv(path: str) -> dict:
    return uv_settings((ROOT / path).read_text(), pyproject=path.endswith("pyproject.toml"))


def bun_days(install: dict) -> float | None:
    seconds = install.get("minimumReleaseAge")
    return seconds / 86400 if isinstance(seconds, int) else None


def uv_days(settings: dict) -> int | None:
    match = re.fullmatch(r"(\d+) days", str(settings.get("exclude-newer", "")))
    return int(match[1]) if match else None


def bun_exception_problems(install: dict) -> list[str]:
    return [
        str(entry)
        for entry in install.get("minimumReleaseAgeExcludes", [])
        if not (isinstance(entry, str) and EXACT_RELEASE.fullmatch(entry))
    ]


def uv_exception_problems(settings: dict) -> list[str]:
    return [
        f"{name} = {value!r}"
        for name, value in settings.get("exclude-newer-package", {}).items()
        if not (isinstance(value, str) and UPLOAD_TIME.fullmatch(value))
    ]


def uv_pip_overrides(settings: dict) -> list[str]:
    """Cooldown keys under [pip], which `uv pip compile` would use instead of the settings above."""
    return sorted({"exclude-newer", "exclude-newer-package"} & settings.get("pip", {}).keys())


def version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def uv_image_tags(dockerfile: str) -> list[str]:
    """The tag of every uv image a Dockerfile builds from or copies from; empty when it names none."""
    return [suffix.removeprefix(":") for suffix in re.findall(r"ghcr\.io/astral-sh/uv(?![\w-])(\S*)", dockerfile)]


def tag_version(tag: str) -> str | None:
    """The uv version a tag names: 0.13.7 and 0.13.7-python3.11-trixie-slim do, a bare variant does not."""
    match = re.match(r"(\d+\.\d+\.\d+)(?:[-@]|$)", tag)
    return match[1] if match else None


def dockerfiles() -> list[Path]:
    """Every tracked Dockerfile, so other checkouts under the repository are not read."""
    tracked = subprocess.run(
        ["git", "ls-files", "--", "Dockerfile*", "**/Dockerfile*"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return [ROOT / path for path in tracked]


def pinned_uv_versions() -> list[tuple[str, str]]:
    """The uv version of every setup-uv step, uv image and pre-commit hook that names one."""
    pins = [
        (str(file.relative_to(ROOT)), named)
        for file in dockerfiles()
        for tag in uv_image_tags(file.read_text())
        if (named := tag_version(tag))
    ]
    files = [*sorted((ROOT / ".github/workflows").glob("*.yml")), ROOT / ".pre-commit-config.yaml"]
    for file in files:
        lines = file.read_text().splitlines()
        for index, line in enumerate(lines):
            if "setup-uv@" not in line and "uv-pre-commit" not in line:
                continue
            for following in lines[index + 1 :]:
                if following.lstrip().startswith("- "):
                    break
                match = re.fullmatch(r"\s*(?:version|rev):\s*\"?([\d.]+)\"?\s*", following)
                if match:
                    pins.append((str(file.relative_to(ROOT)), match[1]))
    return pins


class DependencyCooldownTests(unittest.TestCase):
    def test_every_resolver_waits_the_same_number_of_days_and_at_least_a_week(self) -> None:
        days = {path: bun_days(bun_install((ROOT / path).read_text())) for path in BUN_CONFIGS}
        days |= {path: uv_days(read_uv(path)) for path in UV_CONFIGS}

        self.assertEqual(len(set(days.values())), 1, days)
        self.assertGreaterEqual(days[BUN_CONFIGS[0]] or 0, 7, days)

    def test_the_repository_has_no_whole_package_exception(self) -> None:
        for path in BUN_CONFIGS:
            self.assertEqual(bun_exception_problems(bun_install((ROOT / path).read_text())), [], path)
        for path in UV_CONFIGS:
            self.assertEqual(uv_exception_problems(read_uv(path)), [], path)
            self.assertEqual(uv_pip_overrides(read_uv(path)), [], path)

    def test_a_pip_section_cannot_replace_the_cooldown(self) -> None:
        text = 'exclude-newer = "7 days"\n\n[pip]\nexclude-newer = false\nexclude-newer-package = { example = false }\n'
        self.assertEqual(uv_pip_overrides(uv_settings(text, pyproject=False)), ["exclude-newer", "exclude-newer-package"])
        nested = '[tool.uv]\nexclude-newer = "7 days"\n\n[tool.uv.pip]\nexclude-newer = false\n'
        self.assertEqual(uv_pip_overrides(uv_settings(nested, pyproject=True)), ["exclude-newer"])
        self.assertEqual(uv_pip_overrides(uv_settings('[pip]\ngenerate-hashes = true\n', pyproject=False)), [])

    def test_a_whole_package_exception_is_rejected_however_it_is_spelled(self) -> None:
        for text in (
            "[install]\nminimumReleaseAgeExcludes = ['example']\n",
            '[install]\nminimumReleaseAgeExcludes = ["@scope/example"]\n',
        ):
            self.assertTrue(bun_exception_problems(bun_install(text)), text)
        for text in (
            "[tool.uv.exclude-newer-package]\nexample = false\n",
            "[tool.uv]\nexclude-newer-package = { example = false }\n",
            '[tool.uv]\nexclude-newer-package = { example = "0 days" }\n',
        ):
            self.assertTrue(uv_exception_problems(uv_settings(text, pyproject=True)), text)
        self.assertTrue(
            uv_exception_problems(uv_settings("[exclude-newer-package]\nexample = false\n", pyproject=False))
        )

    def test_an_exception_for_one_release_is_accepted(self) -> None:
        bun = "[install]\nminimumReleaseAgeExcludes = ['example@1.2.3', \"@scope/example@1.2.3-rc.1\"]\n"
        self.assertEqual(bun_exception_problems(bun_install(bun)), [])
        uv = '[tool.uv.exclude-newer-package]\nexample = "2026-11-17T20:24:24Z"\n'
        self.assertEqual(uv_exception_problems(uv_settings(uv, pyproject=True)), [])

    def test_every_pinned_uv_meets_the_version_the_backend_requires(self) -> None:
        required = re.fullmatch(r">=([\d.]+)", read_uv("backend/pyproject.toml").get("required-version", ""))
        self.assertIsNotNone(required, "backend/pyproject.toml sets required-version as a minimum")

        pins = pinned_uv_versions()
        self.assertGreater(len(pins), 1, pins)
        self.assertIn("backend/Dockerfile", [path for path, _ in pins])
        for path, pinned in pins:
            self.assertGreaterEqual(version(pinned), version(required[1]), f"{path} pins uv {pinned}")

    def test_a_uv_image_names_its_version(self) -> None:
        # A floating tag such as python3.11-bookworm-slim can stop following uv releases.
        for file in dockerfiles():
            for tag in uv_image_tags(file.read_text()):
                self.assertIsNotNone(tag_version(tag), f"{file.relative_to(ROOT)} builds on uv:{tag}")
        floating = "FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder"
        self.assertEqual([tag_version(tag) for tag in uv_image_tags(floating)], [None])
        self.assertEqual(uv_image_tags("COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/"), ["0.13.7"])
        self.assertEqual(tag_version("0.14.0-python3.11-trixie-slim"), "0.14.0")
        self.assertEqual(tag_version("0.14.0@sha256:0123"), "0.14.0")
        untagged = "COPY --from=ghcr.io/astral-sh/uv /uv /uvx /bin/"
        self.assertEqual([tag_version(tag) for tag in uv_image_tags(untagged)], [None])


if __name__ == "__main__":
    unittest.main()
