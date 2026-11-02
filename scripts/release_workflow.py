#!/usr/bin/env python3
"""Reviewed release requests -> immutable tags -> verified publication -> history PRs.

Run trusted code from develop. Release checkouts are data: never execute their
scripts or install their dependencies. GitHub App credentials stay in this job.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TypeAlias
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from scripts.check_whats_new import RELEASES_PATH, check
from scripts.release_bundle import bundle, environment, may_promote
from scripts.release_notes import Notes, finalize, port

Json: TypeAlias = "None | bool | int | float | str | list[Json] | dict[str, Json]"
Object: TypeAlias = dict[str, Json]
REQUEST_PATH = ".github/release-request.json"
SHA = re.compile(r"[0-9a-f]{40}")
PREPARATION_LABELS: list[Json] = ["kind:chore", "ci", "documentation"]
HISTORY_LABELS: list[Json] = ["documentation"]


class ReleaseError(Exception):
    """Stop safely; retry the same workflow after correcting the reported cause."""


def obj(value: Json) -> Object:
    if not isinstance(value, dict):
        raise ReleaseError("Expected a JSON object")
    return value


def text(value: Json) -> str:
    if not isinstance(value, str):
        raise ReleaseError("Expected a JSON string")
    return value


def rows(value: Json) -> list[Object]:
    if not isinstance(value, list):
        raise ReleaseError("Expected a JSON array")
    return [obj(item) for item in value]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, stderr=subprocess.PIPE, timeout=60
    ).strip()


@dataclass(frozen=True)
class Version:
    value: str

    def __post_init__(self) -> None:
        if not re.fullmatch(
            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", self.value
        ):
            raise ReleaseError("Use a final version without v, for example 2.4.0")

    @property
    def tag(self) -> str:
        return f"v{self.value}"

    @property
    def branch(self) -> str:
        return "release/v" + self.value.rsplit(".", 1)[0]


@dataclass(frozen=True)
class ReleaseRequest:
    version: Version
    base_sha: str

    def __post_init__(self) -> None:
        if not SHA.fullmatch(self.base_sha):
            raise ReleaseError("A release request requires its full base commit")

    @property
    def branch(self) -> str:
        return f"automation/release-{self.version.tag}-{self.base_sha[:12]}"

    def content(self) -> str:
        return (
            json.dumps(
                {"version": self.version.value, "base_sha": self.base_sha}, indent=2
            )
            + "\n"
        )


class GitHub:
    def __init__(
        self, repository: str, token: str, api: str = "https://api.github.com"
    ) -> None:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ReleaseError("Invalid GitHub repository")
        self.repository = repository
        self.url = f"{api}/repos/{repository}"
        self.token = token

    def request(self, method: str, path: str, data: Object | None = None) -> Json:
        request = Request(
            self.url + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            error.close()
            raise

    def optional(self, path: str) -> Object | None:
        try:
            return obj(self.request("GET", path))
        except HTTPError as error:
            if error.code != 404:
                raise
            return None

    def pages(self, path: str) -> Iterator[Object]:
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):
            batch = rows(
                self.request("GET", f"{path}{separator}per_page=100&page={page}")
            )
            yield from batch
            if len(batch) < 100:
                return
        raise ReleaseError("GitHub pagination exceeded 10,000 results")

    def branch_sha(self, branch: str) -> str:
        ref = obj(self.request("GET", "/git/ref/heads/" + quote(branch, safe="")))
        return text(obj(ref["object"])["sha"])

    def tag_sha(self, version: Version) -> str | None:
        ref = self.optional("/git/ref/tags/" + version.tag)
        if ref is None:
            return None
        target = obj(ref["object"])
        while target["type"] == "tag":
            target = obj(
                obj(self.request("GET", "/git/tags/" + text(target["sha"])))["object"]
            )
        if target["type"] != "commit":
            raise ReleaseError("A release tag must point to a commit")
        return text(target["sha"])

    def release(self, version: Version) -> Object | None:
        # Listing also finds drafts before their tag has been created.
        return next(
            (r for r in self.pages("/releases") if r["tag_name"] == version.tag), None
        )


@contextmanager
def checkout(root: Path, sha: str) -> Iterator[Path]:
    ensure_commit(root, sha)
    with tempfile.TemporaryDirectory(prefix="eneo-release-") as temporary:
        target = Path(temporary) / "source"
        git(
            root,
            "-c",
            "core.hooksPath=/dev/null",
            "worktree",
            "add",
            "--detach",
            str(target),
            sha,
        )
        try:
            yield target
        finally:
            git(root, "worktree", "remove", "--force", str(target))


def ensure_commit(root: Path, sha: str) -> None:
    if not SHA.fullmatch(sha):
        raise ReleaseError("A full source commit is required")
    try:
        git(root, "cat-file", "-e", sha + "^{commit}")
    except subprocess.CalledProcessError:
        # Develop may advance while artifacts are verified. Fetch that exact
        # commit with the job token, without storing credentials in Git config.
        git(
            root,
            "-c",
            "credential.helper=",
            "-c",
            "credential.helper=!gh auth git-credential",
            "fetch",
            "--no-tags",
            "origin",
            sha,
        )


def request_at(root: Path, sha: str) -> ReleaseRequest | None:
    ensure_commit(root, sha)
    if not git(root, "ls-tree", "--name-only", sha, "--", REQUEST_PATH):
        return None  # Already shipped release branches have no managed request.
    request = obj(json.loads(git(root, "show", f"{sha}:{REQUEST_PATH}")))
    if set(request) != {"version", "base_sha"}:
        raise ReleaseError("A release request contains its version and base_sha")
    return ReleaseRequest(Version(text(request["version"])), text(request["base_sha"]))


def managed_tag(ref: str, request: ReleaseRequest | None) -> bool:
    if not ref.startswith("refs/tags/") or "-" in ref.removeprefix("refs/tags/"):
        return False
    if request is None or ref != "refs/tags/" + request.version.tag:
        raise ReleaseError(
            "Final tags require a matching reviewed release request; use Prepare and Publish Release"
        )
    return True


@dataclass(frozen=True)
class Run:
    id: int
    sha: str
    branch: str
    name: str

    @classmethod
    def from_event(cls, event: Object, repository: str) -> Run | None:
        run = obj(event["workflow_run"])
        if (
            run["conclusion"] != "success"
            or run["status"] != "completed"
            or run["event"] != "push"
            or obj(run["head_repository"])["full_name"] != repository
        ):
            return None
        name = text(run["name"])
        paths = {
            "CI": ".github/workflows/ci.yml",
            "Build and Push Docker Images": ".github/workflows/build_and_push_images.yml",
        }
        if name not in paths or run["path"] != paths[name]:
            return None
        run_id = run["id"]
        if not isinstance(run_id, int) or not SHA.fullmatch(text(run["head_sha"])):
            raise ReleaseError("Invalid workflow run identity")
        return cls(run_id, text(run["head_sha"]), text(run["head_branch"]), name)


class Releases:
    def __init__(self, root: Path, github: GitHub) -> None:
        self.root = root
        self.github = github

    def pull_requests(self, branch: str) -> list[Object]:
        query = urlencode(
            {
                "state": "all",
                "head": self.github.repository.split("/")[0] + ":" + branch,
            }
        )
        return list(self.github.pages("/pulls?" + query))

    def notes_pr(
        self,
        branch: str,
        base: str,
        changes: dict[str, str],
        title: str,
        body: str,
        base_sha: str,
        labels: list[Json],
    ) -> Object:
        existing = self.pull_requests(branch)
        if existing:
            pr = existing[0]
            if (
                obj(pr["base"])["ref"] != base
                or obj(obj(pr["head"])["repo"])["full_name"] != self.github.repository
            ):
                raise ReleaseError(
                    "The automation branch belongs to a different pull request"
                )
            if pr["state"] != "open":
                raise ReleaseError(
                    "The automation PR is closed; inspect it before preparing again"
                )
        else:
            ref = "/git/ref/heads/" + quote(branch, safe="")
            previous = self.github.optional(ref)
            if previous:
                sha = text(obj(previous["object"])["sha"])
                for path, content in changes.items():
                    file = obj(
                        self.github.request(
                            "GET", "/contents/" + path + "?" + urlencode({"ref": sha})
                        )
                    )
                    if base64.b64decode(text(file["content"])).decode() != content:
                        raise ReleaseError(
                            "An unfinished automation branch has different content; inspect it before retrying"
                        )
            else:
                if self.github.branch_sha(base) != base_sha:
                    raise ReleaseError(
                        "The target branch advanced during preparation; retry from its current head"
                    )
                commit = obj(self.github.request("GET", "/git/commits/" + base_sha))
                tree = obj(
                    self.github.request(
                        "POST",
                        "/git/trees",
                        {
                            "base_tree": obj(commit["tree"])["sha"],
                            "tree": [
                                {
                                    "path": path,
                                    "mode": "100644",
                                    "type": "blob",
                                    "content": content,
                                }
                                for path, content in changes.items()
                            ],
                        },
                    )
                )
                created = obj(
                    self.github.request(
                        "POST",
                        "/git/commits",
                        {
                            "message": title,
                            "tree": tree["sha"],
                            "parents": [base_sha],
                        },
                    )
                )
                self.github.request(
                    "POST",
                    "/git/refs",
                    {"ref": "refs/heads/" + branch, "sha": created["sha"]},
                )
            pr = obj(
                self.github.request(
                    "POST",
                    "/pulls",
                    {"head": branch, "base": base, "title": title, "body": body},
                )
            )
        self.github.request(
            "POST", f"/issues/{pr['number']}/labels", {"labels": labels}
        )
        print(text(pr["html_url"]))
        return pr

    def prepare(self, version: Version) -> None:
        tagged = self.github.tag_sha(version)
        if tagged:
            self.tag(version, tagged)
            return
        sha = self.github.branch_sha(version.branch)
        prior_request = request_at(self.root, sha)
        if prior_request and prior_request.version == version:
            merged = self.pull_requests(prior_request.branch)
            if any(
                p.get("merge_commit_sha") == sha and p.get("merged_at") for p in merged
            ):
                self.tag(version, sha)
                return
        if self.github.release(version) is not None:
            raise ReleaseError(
                "A release already exists without its tag; inspect it before proceeding"
            )
        request = ReleaseRequest(version, sha)
        existing = self.pull_requests(request.branch)
        if existing:
            pr = existing[0]
            if pr.get("merged_at"):
                self.tag(version, text(pr["merge_commit_sha"]))
                return
            if pr["state"] != "open":
                raise ReleaseError("The preparation PR was closed without merging")
            candidate = text(obj(pr["head"])["sha"])
            if request_at(self.root, candidate) != request:
                raise ReleaseError(
                    "The preparation request was changed; review it before retrying"
                )
            with checkout(self.root, candidate) as source:
                self.validate(source, version)
            self.notes_pr(
                request.branch, version.branch, {}, "", "", sha, PREPARATION_LABELS
            )
            return  # Preserve its reviewed date, commit and any ongoing checks.
        previous = self.github.optional(
            "/git/ref/heads/" + quote(request.branch, safe="")
        )
        source_sha = text(obj(previous["object"])["sha"]) if previous else sha
        with checkout(self.root, source_sha) as source:
            notes = Notes(source)
            if not finalize(notes, version.value):
                raise ReleaseError("Release notes failed final validation")
            self.validate(source, version)
            changes = {
                str(RELEASES_PATH): notes.path.read_text(),
                REQUEST_PATH: request.content(),
            }
        self.notes_pr(
            request.branch,
            version.branch,
            changes,
            f"chore(release): prepare {version.tag}",
            f"## Changes\n\nPrepare `{version.tag}` from `{version.branch}` at `{sha}`. "
            "The request records the reviewed release version and base commit; "
            "the existing notes own its date.\n\n"
            "Merge after review and green CI. The successful release-branch CI run "
            "creates an immutable tag and draft release. Publication waits for "
            "images, smoke tests and SBOMs.\n\n"
            "## User-facing\n\nThe existing release notes receive their publication date.\n\n"
            "## Testing\n\nThe final-tag notes validator passed before this PR was created.\n",
            sha,
            PREPARATION_LABELS,
        )

    @staticmethod
    def validate(source: Path, version: Version) -> None:
        workflow = source / ".github/workflows/build_and_push_images.yml"
        controller = source / "scripts/release_workflow.py"
        if (
            not workflow.is_file()
            or not controller.is_file()
            or "python3 -m scripts.release_workflow identify"
            not in workflow.read_text()
            or "if: needs.release.outputs.managed != 'true'" not in workflow.read_text()
        ):
            raise ReleaseError(
                "This release branch predates managed publication; backport the release controller and image coordinator before preparing it"
            )
        _, errors = check(source, version.branch, version.tag)
        if errors:
            raise ReleaseError("; ".join(errors))

    def tag(self, version: Version, sha: str) -> None:
        request = request_at(self.root, sha)
        if request is None or request.version != version:
            raise ReleaseError("The candidate has no matching release request")
        previous = self.github.tag_sha(version)
        if previous is not None and previous != sha:
            raise ReleaseError(
                "The tag already identifies another commit; refusing to move it"
            )
        if previous is None and self.github.branch_sha(version.branch) != sha:
            raise ReleaseError(
                "The release branch advanced; prepare and review the current candidate"
            )
        candidates = self.github.pages("/commits/" + sha + "/pulls")
        reviewed = next(
            (
                pr
                for pr in candidates
                if (
                    pr.get("merged_at")
                    and pr.get("merge_commit_sha") == sha
                    and obj(pr["base"])["ref"] == version.branch
                    and obj(pr["head"])["ref"] == request.branch
                    and obj(obj(pr["head"])["repo"])["full_name"]
                    == self.github.repository
                )
            ),
            None,
        )
        if reviewed is None:
            raise ReleaseError("The candidate must be the merged preparation PR")
        changed = {
            text(f["filename"])
            for f in self.github.pages(f"/pulls/{reviewed['number']}/files")
        }
        if REQUEST_PATH not in changed or changed - {REQUEST_PATH, str(RELEASES_PATH)}:
            raise ReleaseError(
                "The preparation PR must only change its request and release notes"
            )
        query = urlencode(
            {"event": "push", "head_sha": sha, "status": "success", "per_page": 100}
        )
        runs = obj(
            self.github.request("GET", "/actions/workflows/ci.yml/runs?" + query)
        )
        if not any(
            r["head_sha"] == sha
            and r["head_branch"] == version.branch
            and r["event"] == "push"
            and r["conclusion"] == "success"
            for r in rows(runs["workflow_runs"])
        ):
            print("Waiting for successful CI on the merged release commit.")
            return
        with checkout(self.root, sha) as source:
            self.validate(source, version)
        release = self.github.release(version)
        if release is None:
            self.github.request(
                "POST",
                "/releases",
                {
                    "tag_name": version.tag,
                    "target_commitish": sha,
                    "name": version.tag,
                    "draft": True,
                    "prerelease": False,
                    "generate_release_notes": True,
                    "make_latest": "false",
                },
            )
        elif release["target_commitish"] != sha:
            raise ReleaseError("An existing release targets another commit")
        if previous is None:
            # POST is create-only. Never PATCH, force-update or delete a release tag.
            self.github.request(
                "POST", "/git/refs", {"ref": "refs/tags/" + version.tag, "sha": sha}
            )
        print(
            f"{version.tag} is pinned to {sha}; publication is waiting for the image workflow."
        )

    def complete(self, version: Version, run: Run) -> None:
        request = request_at(self.root, run.sha)
        if (
            self.github.tag_sha(version) != run.sha
            or request is None
            or request.version != version
        ):
            raise ReleaseError("The successful build no longer matches the release tag")
        actual = obj(self.github.request("GET", f"/actions/runs/{run.id}"))
        verified = Run.from_event({"workflow_run": actual}, self.github.repository)
        if (
            verified != run
            or run.name != "Build and Push Docker Images"
            or run.branch != version.tag
        ):
            raise ReleaseError(
                "Publication requires the successful tag-push image workflow"
            )
        release = self.github.release(version)
        if (
            release is None
            or release["target_commitish"] != run.sha
            or release["prerelease"]
        ):
            raise ReleaseError("The build has no matching draft release")
        required = {
            "release.json",
            "release.env",
            "SBOM-SHA256SUMS.txt",
            "IMAGE-DIGESTS.txt",
        }
        assets = {text(a["name"]) for a in rows(release["assets"])}
        if not required <= assets:
            raise ReleaseError("Release bundle or SBOM assets are incomplete")
        with tempfile.TemporaryDirectory(prefix="eneo-publish-") as directory:
            subprocess.run(
                [
                    "gh",
                    "release",
                    "download",
                    version.tag,
                    "--repo",
                    self.github.repository,
                    "--pattern",
                    "release.json",
                    "--pattern",
                    "release.env",
                    "--pattern",
                    "SBOM-SHA256SUMS.txt",
                    "--dir",
                    directory,
                ],
                check=True,
                timeout=120,
            )
            path = Path(directory) / "release.json"
            subprocess.run(
                [
                    "gh",
                    "attestation",
                    "verify",
                    str(path),
                    "--repo",
                    self.github.repository,
                    "--signer-workflow",
                    f"{self.github.repository}/.github/workflows/build_and_push_images.yml",
                    "--source-ref",
                    "refs/tags/" + version.tag,
                    "--source-digest",
                    run.sha,
                ],
                check=True,
                timeout=120,
            )
            recorded = obj(json.loads(path.read_text()))
            images = {
                component: text(image)
                for component, image in obj(recorded["images"]).items()
            }
            if recorded != bundle(version.value, run.sha, images):
                raise ReleaseError(
                    "The attested release bundle names a different version or source"
                )
            if (Path(directory) / "release.env").read_text() != environment(
                version.value, run.sha, images
            ):
                raise ReleaseError(
                    "The deployment environment does not match the attested bundle"
                )
            sums = Path(directory) / "SBOM-SHA256SUMS.txt"
            subprocess.run(
                [
                    "gh",
                    "attestation",
                    "verify",
                    str(sums),
                    "--repo",
                    self.github.repository,
                    "--signer-workflow",
                    f"{self.github.repository}/.github/workflows/release_sbom.yml",
                    "--source-ref",
                    "refs/tags/" + version.tag,
                    "--source-digest",
                    run.sha,
                ],
                check=True,
                timeout=120,
            )
            checksums: dict[str, str] = {}
            for line in sums.read_text().splitlines():
                match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
                if not match or match[2] in checksums or match[2] in {".", ".."}:
                    raise ReleaseError("Invalid or duplicate SBOM checksum entry")
                checksums[match[2]] = match[1]
            if "IMAGE-DIGESTS.txt" not in checksums or not set(checksums) <= assets:
                raise ReleaseError("The signed SBOM inventory has missing assets")
            command = [
                "gh",
                "release",
                "download",
                version.tag,
                "--repo",
                self.github.repository,
                "--dir",
                directory,
            ]
            for name in checksums:
                command.extend(["--pattern", name])
            subprocess.run(command, check=True, timeout=120)
            for name, checksum in checksums.items():
                with (Path(directory) / name).open("rb") as artifact:
                    if hashlib.file_digest(artifact, "sha256").hexdigest() != checksum:
                        raise ReleaseError(
                            f"SBOM asset {name} does not match its attested checksum"
                        )
        if self.github.tag_sha(version) != run.sha:
            raise ReleaseError("The release tag moved during bundle verification")
        newest = may_promote(
            "refs/tags/" + version.tag,
            run.sha,
            [version.tag]
            + [
                text(r["tag_name"])
                for r in self.github.pages("/releases")
                if not r["draft"] and not r["prerelease"]
            ],
            None,
        )
        if release["draft"]:
            self.github.request(
                "PATCH",
                f"/releases/{release['id']}",
                {"draft": False, "make_latest": "true" if newest else "false"},
            )
        print(f"Published {version.tag} from verified build {run.id}.")

    def port(self, version: Version, sha: str) -> None:
        if self.github.tag_sha(version) != sha:
            raise ReleaseError("The release tag moved before history synchronisation")
        release = self.github.release(version)
        if release is None or release["draft"] or release["target_commitish"] != sha:
            raise ReleaseError("History is only updated after publication")
        base_sha = self.github.branch_sha("develop")
        with checkout(self.root, base_sha) as source:
            released = obj(json.loads(git(source, "show", f"{sha}:{RELEASES_PATH}")))
            if not any(
                r["version"] == version.value for r in rows(released["releases"])
            ):
                print("This hotfix has no separate user-facing notes to port.")
                return
            notes = Notes(source)
            if not port(notes, version.value, sha):
                raise ReleaseError("Release history failed validation")
            content = notes.path.read_text()
            if content == notes.original:
                print("Develop already records this release.")
                return
        self.notes_pr(
            f"automation/port-{version.tag}",
            "develop",
            {str(RELEASES_PATH): content},
            f"docs(whats-new): record the published {version.tag} release",
            f"## Changes\n\nPort the dated `{version.tag}` notes from immutable commit "
            f"`{sha}` to develop using the canonical port command. "
            "Entries that have not shipped remain in next.\n\n"
            "## User-facing\n\nThe app and documentation distinguish released features "
            "from upcoming changes.\n\n"
            "## Testing\n\nThe develop release-notes validator passed.\n",
            base_sha,
            HISTORY_LABELS,
        )


def plan(
    root: Path, event: Object, event_name: str, repository: str, version_input: str
) -> tuple[str, Version | None, Run | None]:
    if event_name == "workflow_dispatch":
        if os.environ["GITHUB_REF"] != "refs/heads/develop":
            raise ReleaseError("Prepare releases from the develop workflow only")
        return "prepare", Version(version_input), None
    run = Run.from_event(event, repository)
    if run is None:
        return "skip", None, None
    request = request_at(root, run.sha)
    if request is None:
        return "skip", None, None
    version = request.version
    if (
        run.name == "CI"
        and run.branch == version.branch
        and git(root, "diff", "--name-only", run.sha + "^", run.sha, "--", REQUEST_PATH)
    ):
        return "tag", version, run
    if run.name == "Build and Push Docker Images" and run.branch == version.tag:
        return "complete", version, run
    return "skip", None, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "run", "port", "identify"])
    args = parser.parse_args()
    root = Path.cwd()
    if args.command == "identify":
        ref = os.environ["GITHUB_REF"]
        request = request_at(root, os.environ["GITHUB_SHA"])
        managed = managed_tag(ref, request)
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"managed={str(managed).lower()}\n")
        return
    event = obj(json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()))
    repository = os.environ["GITHUB_REPOSITORY"]
    operation, version, run = plan(
        root,
        event,
        os.environ["GITHUB_EVENT_NAME"],
        repository,
        os.environ.get("RELEASE_VERSION", ""),
    )
    if args.command == "plan":
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(
                f"operation={operation}\nversion={version.value if version else ''}\nsha={run.sha if run else ''}\n"
            )
        print(f"Release operation: {operation}")
        return
    if operation == "skip" or version is None:
        return
    releases = Releases(
        root,
        GitHub(
            repository,
            os.environ["GH_TOKEN"],
            os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        ),
    )
    if args.command == "port":
        if operation != "complete" or run is None:
            raise ReleaseError("History requires a completed image publication")
        releases.port(version, run.sha)
    elif operation == "prepare":
        releases.prepare(version)
    elif run is not None and operation == "tag":
        releases.tag(version, run.sha)
    elif run is not None:
        releases.complete(version, run)


if __name__ == "__main__":
    try:
        main()
    except (
        ReleaseError,
        HTTPError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"Release stopped safely: {error}") from error
