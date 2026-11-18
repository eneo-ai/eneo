"""Every package resolver waits the same time for a new release, without whole-package exceptions."""

from __future__ import annotations

import re
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


def version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def pinned_uv_versions() -> list[tuple[str, str]]:
    """The uv version of every setup-uv step and of the pre-commit hook that names one."""
    pins = []
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
        for path, pinned in pins:
            self.assertGreaterEqual(version(pinned), version(required[1]), f"{path} pins uv {pinned}")


if __name__ == "__main__":
    unittest.main()
