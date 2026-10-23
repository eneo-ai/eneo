#!/usr/bin/env python3
"""Prepare protected deployment configuration without replacing operator choices."""

import argparse
import fcntl
import os
import re
import secrets
import tempfile
from pathlib import Path


def assignments(text: str) -> dict[str, str]:
    return dict(
        re.findall(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*)$", text, re.M)
    )


def nonempty(value: str) -> bool:
    value = value.strip()
    if value.startswith(('"', "'")):
        return bool(value[1:].split(value[0], 1)[0])
    return bool(value.split(" #", 1)[0].strip())


def configure(directory: Path, version: str | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".setup.lock", "a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / ".env"
        if path.is_symlink():
            raise ValueError("Refusing to replace a symbolic-link configuration")
        text = path.read_text() if path.exists() else ""
        existing = assignments(text)
        backend_path = directory / "env_backend.env"
        previous = (
            assignments(backend_path.read_text()) if backend_path.exists() else {}
        )
        additions = {
            key: previous[key]
            for key in ("TOOL_RUNTIME_URL", "FILE_REFERENCE_BASE_URL")
            if key not in existing and nonempty(previous.get(key, ""))
        }
        if not nonempty(existing.get("TOOL_RUNTIME_TOKEN", "")):
            old_token = previous.get("TOOL_RUNTIME_TOKEN", "")
            additions["TOOL_RUNTIME_TOKEN"] = (
                old_token if nonempty(old_token) else secrets.token_hex(32)
            )
        if version and "ENEO_VERSION" not in existing:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", version):
                raise ValueError("Invalid image version")
            additions["ENEO_VERSION"] = version.removeprefix("v")
        # Replace only an empty token assignment; all other existing lines survive.
        if "TOOL_RUNTIME_TOKEN" in additions:
            text = re.sub(
                r"^[ \t]*(?:export\s+)?TOOL_RUNTIME_TOKEN[ \t]*=.*\n?",
                "",
                text,
                flags=re.M,
            )
        if additions:
            text = (
                text.rstrip("\n")
                + "\n"
                + "".join(f"{k}={v}\n" for k, v in additions.items())
            )
        fd, temporary = tempfile.mkstemp(prefix=".env-", dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(__file__).parent)
    parser.add_argument("--version")
    args = parser.parse_args()
    configure(args.directory, args.version)
    print("Deployment configuration prepared. Existing settings were preserved.")
