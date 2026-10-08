#!/usr/bin/env python3
"""One version, verified images, and a complete deployment bundle. Stdlib only."""

from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

COMPONENTS = ("backend", "frontend", "tool-runtime")
REGISTRY = "ghcr.io/eneo-ai/eneo-"
SHA = re.compile(r"[0-9a-f]{40}")
SEMVER = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?"
)


def resolve(ref: str, revision: str) -> dict[str, str]:
    if not SHA.fullmatch(revision):
        raise ValueError("A full source revision is required")
    if ref.startswith("refs/tags/"):
        tag = ref.removeprefix("refs/tags/")
        if not SEMVER.fullmatch(tag):
            raise ValueError("Release tags must be semantic versions")
        version = tag.removeprefix("v")
        alias = "latest" if "-" not in version else ""
    elif ref.startswith("refs/heads/"):
        alias = re.sub(
            r"[^a-z0-9_.-]", "-", ref.removeprefix("refs/heads/").lower()
        ).strip(".-")[:80]
        if not alias:
            raise ValueError("Invalid branch name")
        version = f"{alias}-{revision[:12]}"
    else:
        raise ValueError("Only branches and release tags can publish")
    return {"version": version, "revision": revision, "alias": alias}


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def inspect(ref: str) -> dict | None:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--raw"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if re.search(r"manifest unknown|not found", result.stderr, re.I):
            return None
        raise RuntimeError(f"Cannot verify registry image {ref}: {result.stderr}")
    return json.loads(result.stdout)


def verify_image(component: str, version: str, revision: str) -> str | None:
    image = REGISTRY + component
    ref = f"{image}:{version}"
    manifest = inspect(ref)
    if manifest is None:
        return None
    digest = json.loads(
        run(
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            ref,
            "--format",
            "{{json .Manifest}}",
        )
    )["digest"]
    children = [
        m
        for m in manifest.get("manifests", [])
        if m.get("platform", {}).get("os") == "linux"
    ]
    expected = {"amd64", "arm64"} if component == "tool-runtime" else {"amd64"}
    if (not children and len(expected) > 1) or (
        children and {m["platform"]["architecture"] for m in children} != expected
    ):
        raise ValueError(f"Unexpected platforms for {ref}")
    for child in children or [{"digest": digest}]:
        config = json.loads(
            run(
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                f"{image}@{child['digest']}",
                "--format",
                "{{json .Image}}",
            )
        )
        labels = config.get("config", {}).get("Labels", {})
        if (
            labels.get("org.opencontainers.image.revision") != revision
            or labels.get("org.opencontainers.image.version") != version
        ):
            raise ValueError(
                f"Refusing to replace {ref}: version or source revision differs"
            )
    return digest


def bundle(version: str, revision: str, images: dict[str, str]) -> dict:
    if set(images) != set(COMPONENTS) or not SHA.fullmatch(revision):
        raise ValueError(
            "A bundle needs all application components and a full revision"
        )
    for component, ref in images.items():
        if not re.fullmatch(
            re.escape(REGISTRY + component) + r"@sha256:[0-9a-f]{64}", ref
        ):
            raise ValueError(f"Invalid immutable image for {component}")
    return {
        "schema_version": 1,
        "version": version,
        "revision": revision,
        "images": images,
    }


def may_promote(
    ref: str, revision: str, tags: list[str], branch_head: str | None
) -> bool:
    if ref.startswith("refs/heads/"):
        return revision == branch_head
    version = ref.removeprefix("refs/tags/").removeprefix("v")
    finals = [
        tuple(map(int, t.removeprefix("v").split(".")))
        for t in tags
        if re.fullmatch(r"v?\d+\.\d+\.\d+", t)
    ]
    return (
        "-" not in version
        and bool(finals)
        and tuple(map(int, version.split("."))) == max(finals)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["resolve", "reuse", "bundle", "promote"])
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--output", default="release-bundle")
    args = parser.parse_args()
    ref, revision = os.environ["GITHUB_REF"], os.environ["GITHUB_SHA"]
    release = resolve(ref, revision)
    version = release["version"]
    if args.command == "resolve":
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            for key, value in release.items():
                out.write(f"{key}={value}\n")
        return
    if args.command == "reuse":
        assert args.component
        digest = verify_image(args.component, version, revision)
        if digest:
            run(
                "gh",
                "attestation",
                "verify",
                f"oci://{REGISTRY}{args.component}@{digest}",
                "--repo",
                os.environ["GITHUB_REPOSITORY"],
            )
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"exists={str(bool(digest)).lower()}\ndigest={digest or ''}\n")
        return
    images = {}
    for component in COMPONENTS:
        digest = verify_image(component, version, revision)
        if not digest:
            raise ValueError(f"Missing image: {component}")
        images[component] = f"{REGISTRY}{component}@{digest}"
    if args.command == "bundle":
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        (output / "release.json").write_text(
            json.dumps(bundle(version, revision, images), indent=2) + "\n"
        )
        lines = [f"ENEO_VERSION={version}", f"ENEO_REVISION={revision}"]
        lines += [
            f"ENEO_{component.upper().replace('-', '_')}_IMAGE={image}"
            for component, image in images.items()
        ]
        (output / "release.env").write_text("\n".join(lines) + "\n")
    else:
        head = None
        if ref.startswith("refs/heads/"):
            remote = run("git", "ls-remote", "origin", ref)
            head = remote.split()[0] if remote else None
        tags = [
            line.split("refs/tags/")[-1]
            for line in run(
                "git", "ls-remote", "--tags", "--refs", "origin"
            ).splitlines()
        ]
        if may_promote(ref, revision, tags, head):
            for component, image in images.items():
                run(
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--tag",
                    f"{REGISTRY}{component}:{release['alias']}",
                    image,
                )


if __name__ == "__main__":
    main()
