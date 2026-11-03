#!/usr/bin/env python3
"""One version, verified images, and a complete deployment bundle. Stdlib only."""

from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

# The backend image includes the optional Vite UI; Svelte keeps its own image.
COMPONENTS = ("backend", "frontend", "tool-runtime")
REGISTRY = "ghcr.io/eneo-ai/eneo-"
SHA = re.compile(r"[0-9a-f]{40}")
# Release versions come only from v-prefixed tags, the ones release rules protect.
SEMVER = re.compile(
    r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?"
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
        # Only develop itself publishes the develop alias, and no branch publishes latest
        # or an alias shaped like a version tag (a release's, or a branch's <name>-<sha>),
        # which another publication writes under that version's own lock.
        if (
            alias == "latest"
            or (alias == "develop" and ref != "refs/heads/develop")
            or re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9a-z.-]+)?", alias)
            or re.search(r"-[0-9a-f]{12}$", alias)
        ):
            raise ValueError(f"{ref} would publish the reserved {alias} alias")
        version = f"{alias}-{revision[:12]}"
    else:
        raise ValueError("Only branches and release tags can publish")
    return {"version": version, "revision": revision, "alias": alias}


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def inspect(ref: str) -> dict | None:
    """One registry read: the manifest's digest and the platform manifests it lists."""
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", ref, "--format", "{{json .Manifest}}"],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if re.search(r"manifest unknown|not found", result.stderr, re.I):
            return None
        raise RuntimeError(f"Cannot verify registry image {ref}: {result.stderr}")
    return json.loads(result.stdout)


def verify_image(component: str, version: str, revision: str) -> str | None:
    """The digest a version tag names, checked as verify_digest checks it."""
    manifest = inspect(f"{REGISTRY}{component}:{version}")
    if manifest is None:
        return None
    return verify_digest(component, manifest["digest"], version, revision, manifest)


def verify_digest(
    component: str,
    digest: str,
    version: str,
    revision: str,
    manifest: dict | None = None,
) -> str:
    """Platforms and labels of the image at an immutable digest.

    Every read after the first names a digest, so a tag that moves meanwhile cannot
    swap in an image that was never checked.
    """
    image = REGISTRY + component
    ref = f"{image}@{digest}"
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid digest for {component}")
    manifest = manifest or inspect(ref)
    if manifest is None or manifest.get("digest") != digest:
        raise ValueError(f"Cannot read {ref}")
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


def may_move_branch_alias(
    revision: str,
    head: str | None,
    destinations: list[str | None],
    contains: Callable[[str, str], bool],
) -> bool:
    """Whether a branch's alias may move to revision, given what each destination names.

    contains(a, b) is true when a is b or an ancestor of b. The candidate must be on
    the branch. Each destination must be absent, at the candidate, behind it, or off
    the branch (left behind by a rebase); one ahead of it refuses the whole move. So a
    retry completes an interrupted promotion but never undoes a newer one.
    """
    if head is None or not contains(revision, head):
        return False
    return all(
        current is None or contains(current, revision) or not contains(current, head)
        for current in destinations
    )


def may_promote(ref: str, revision: str, tags: list[str]) -> bool:
    """Whether a final release tag is the newest final release."""
    if not ref.startswith("refs/tags/"):
        raise ValueError("Branch aliases move by may_move_branch_alias")
    version = ref.removeprefix("refs/tags/").removeprefix("v")
    finals = [
        tuple(map(int, t.removeprefix("v").split(".")))
        for t in tags
        if re.fullmatch(r"v\d+\.\d+\.\d+", t)
    ]
    return (
        "-" not in version
        and bool(finals)
        and tuple(map(int, version.split("."))) == max(finals)
    )


def alias_state(component: str, alias: str) -> tuple[str | None, str | None]:
    """The digest and source revision an alias names, or (None, None) when it is absent.

    An alias whose platforms carry no revision, or different ones, is an error, not an
    absent alias: nothing is written over what cannot be read.
    """
    image = REGISTRY + component
    manifest = inspect(f"{image}:{alias}")
    if manifest is None:
        return None, None
    children = [m for m in manifest.get("manifests", []) if m.get("platform", {}).get("os") == "linux"]
    revisions = {
        json.loads(
            run("docker", "buildx", "imagetools", "inspect", f"{image}@{child['digest']}", "--format", "{{json .Image}}")
        ).get("config", {}).get("Labels", {}).get("org.opencontainers.image.revision")
        for child in children or [{"digest": manifest["digest"]}]
    }
    if len(revisions) != 1 or not SHA.fullmatch(next(iter(revisions)) or ""):
        raise ValueError(f"Cannot read the source revision of {image}:{alias}")
    return manifest["digest"], revisions.pop()


def contains(ancestor: str, descendant: str) -> bool:
    """Whether ancestor is descendant or one of its ancestors in this clone."""
    check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant], capture_output=True
    )
    return check.returncode == 0


def write_aliases(alias: str, images: dict[str, str]) -> None:
    """Points every component's alias at the bundled digest, then checks all of them."""
    for component, image in images.items():
        run("docker", "buildx", "imagetools", "create", "--tag", f"{REGISTRY}{component}:{alias}", image)
    for component, image in images.items():
        if alias_state(component, alias)[0] != image.rsplit("@", 1)[1]:
            raise ValueError(f"{REGISTRY}{component}:{alias} does not name {image}")


def environment(version: str, revision: str, images: dict[str, str]) -> str:
    """The deployment environment is derived from the verified bundle."""
    bundle(version, revision, images)
    lines = [f"ENEO_VERSION={version}", f"ENEO_REVISION={revision}"]
    lines += [
        f"ENEO_{component.upper().replace('-', '_')}_IMAGE={images[component]}"
        for component in COMPONENTS
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["resolve", "reuse", "bundle", "promote"])
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--output", default="release-bundle")
    parser.add_argument(
        "--ref", help="Explicit source ref for default-branch release reconciliation"
    )
    parser.add_argument(
        "--revision", help="Explicit source commit for default-branch release reconciliation"
    )
    parser.add_argument(
        "--digest", action="append", default=[], metavar="COMPONENT=DIGEST",
        help="A component's digest from the job that built or reused it (bundle)",
    )
    parser.add_argument(
        "--bundle", help="The release.json this run verified and smoke tested (promote)",
    )
    parser.add_argument(
        "--published-releases", action="store_true",
        help="Promote among successfully published releases, excluding unfinished final tags",
    )
    args = parser.parse_args()
    ref = args.ref or os.environ["GITHUB_REF"]
    revision = args.revision or os.environ["GITHUB_SHA"]
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
            try:
                run(
                    "gh",
                    "attestation",
                    "verify",
                    f"oci://{REGISTRY}{args.component}@{digest}",
                    "--repo",
                    os.environ["GITHUB_REPOSITORY"],
                )
            except subprocess.CalledProcessError:
                # A previous run can push the image and fail before attesting it.
                # Rebuild from this checkout; never reuse an unverified digest.
                # Version/source/platform mismatches above remain fatal.
                print(
                    f"Cannot verify provenance for {args.component}@{digest}; "
                    "rebuilding from the matching source revision."
                )
                digest = None
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            out.write(f"exists={str(bool(digest)).lower()}\ndigest={digest or ''}\n")
        return
    images = {}
    if args.command == "bundle":
        # The digests the component jobs built or reused, never their tags again.
        digests = dict(item.split("=", 1) for item in args.digest)
        for component in COMPONENTS:
            if not digests.get(component):
                raise ValueError(f"Missing image: {component}")
            digest = verify_digest(component, digests[component], version, revision)
            images[component] = f"{REGISTRY}{component}@{digest}"
    elif args.bundle:
        # Promote exactly what this run bundled and smoke tested.
        recorded = json.loads(Path(args.bundle).read_text())
        images = {component: str(image) for component, image in recorded["images"].items()}
        if recorded != bundle(version, revision, images):
            raise ValueError("The bundle names a different version or source")
        # Each image again, by digest: a bundle file that changed between jobs cannot
        # point an alias at an image of another version or revision.
        for component, image in images.items():
            verify_digest(component, image.rsplit("@", 1)[1], version, revision)
    else:
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
        (output / "release.env").write_text(environment(version, revision, images))
    elif ref.startswith("refs/heads/"):
        # Decided on every attempt, retries included, under the alias lock and against
        # the branch as it is now; every destination is read before anything is written.
        alias = release["alias"]
        destinations = [alias_state(component, alias)[1] for component in COMPONENTS]
        head = None
        if run("git", "ls-remote", "origin", ref):
            run("git", "fetch", "--quiet", "--no-tags", "origin", ref)
            head = run("git", "rev-parse", "FETCH_HEAD")
        if may_move_branch_alias(revision, head, destinations, contains):
            write_aliases(alias, images)
        else:
            print(f"{alias} stays at {destinations}: {revision} is not newer on {ref}")
    else:
        if args.published_releases:
            if not ref.startswith("refs/tags/"):
                raise ValueError("Published release promotion requires a tag")
            tags = run(
                "gh", "api", "--paginate",
                f"repos/{os.environ['GITHUB_REPOSITORY']}/releases",
                "--jq", '.[] | select(.draft == false and .prerelease == false) | .tag_name',
            ).splitlines()
        else:
            tags = [
                line.split("refs/tags/")[-1]
                for line in run(
                    "git", "ls-remote", "--tags", "--refs", "origin"
                ).splitlines()
            ]
        if may_promote(ref, revision, tags):
            write_aliases(release["alias"], images)


if __name__ == "__main__":
    main()
