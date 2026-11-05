"""Release lifecycle contracts against real Git and an offline GitHub REST server."""

from __future__ import annotations

import base64
import copy
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit

from scripts.release_bundle import COMPONENTS, REGISTRY, bundle, environment
from scripts.release_notes import format_json
from scripts.release_workflow import (
    GitHub,
    Json,
    Object,
    ReleaseError,
    ReleaseRequest,
    Releases,
    Run,
    Version,
    identify,
    managed_tag,
    obj,
    plan,
    request_at,
    text,
)
from scripts.tests.test_check_whats_new import ENTRY, REPO_ROOT, _RepoCase

NOTES = "frontend/packages/whats-new/releases.json"
REPOSITORY = "eneo-ai/eneo"


class GitHubFixture:
    """Implement the REST boundaries used here, persisting commits in real Git."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.prs: list[Object] = []
        self.releases: list[Object] = []
        self.runs: list[Object] = []
        self.fail: tuple[str, str] | None = None

    def git(
        self, *args: str, input: str | None = None, env: dict[str, str] | None = None
    ) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null", *args],
            text=True,
            input=input,
            env=env,
            stderr=subprocess.PIPE,
        ).strip()

    def ci(self, sha: str, name: str = "CI", conclusion: str = "success") -> Object:
        run: Object = {
            "id": len(self.runs) + 1,
            "head_sha": sha,
            "head_branch": "release/v2.4" if name == "CI" else "v2.4.0",
            "head_repository": {"full_name": REPOSITORY},
            "name": name,
            "event": "push",
            "conclusion": conclusion,
            "status": "completed",
            "path": ".github/workflows/ci.yml"
            if name == "CI"
            else ".github/workflows/build_and_push_images.yml",
        }
        self.runs.append(run)
        return run

    def merge(self, pr: Object) -> str:
        base = text(obj(pr["base"])["ref"])
        tree = self.git("rev-parse", text(obj(pr["head"])["sha"]) + "^{tree}")
        sha = self.git(
            "commit-tree",
            tree,
            "-p",
            self.git("rev-parse", base),
            "-m",
            "Reviewed release",
        )
        self.git("update-ref", "refs/heads/" + base, sha)
        pr.update(
            {
                "state": "closed",
                "merged_at": "2026-11-02T00:00:00Z",
                "merge_commit_sha": sha,
            }
        )
        return sha

    def request(
        self, method: str, path: str, query: dict[str, list[str]], data: Object
    ) -> tuple[int, Json]:
        if self.fail == (method, path):
            self.fail = None
            return 503, {"message": "Injected transport failure"}
        if method == "GET":
            if path.startswith("/git/ref/"):
                try:
                    sha = self.git(
                        "rev-parse", "refs/" + path.removeprefix("/git/ref/")
                    )
                    return 200, {
                        "object": {"sha": sha, "type": self.git("cat-file", "-t", sha)}
                    }
                except subprocess.CalledProcessError:
                    return 404, {"message": "Not found"}
            if path.startswith("/contents/"):
                content = (
                    self.git(
                        "show", query["ref"][0] + ":" + path.removeprefix("/contents/")
                    )
                    + "\n"
                )
                return 200, {"content": base64.b64encode(content.encode()).decode()}
            if path.startswith("/git/commits/"):
                return 200, {
                    "tree": {
                        "sha": self.git("rev-parse", path.rsplit("/", 1)[1] + "^{tree}")
                    }
                }
            if path.startswith("/git/tags/"):
                return 200, {
                    "object": {
                        "type": "commit",
                        "sha": self.git("rev-parse", path.rsplit("/", 1)[1] + "^{}"),
                    }
                }
            if path == "/pulls":
                found = self.prs
                if "head" in query:
                    branch = query["head"][0].split(":", 1)[1]
                    found = [p for p in found if obj(p["head"])["ref"] == branch]
                if "base" in query:
                    found = [
                        p for p in found if obj(p["base"])["ref"] == query["base"][0]
                    ]
                if query.get("state", ["all"])[0] != "all":
                    found = [p for p in found if p["state"] == query["state"][0]]
                return 200, found
            if path.startswith("/commits/") and path.endswith("/pulls"):
                return 200, [
                    p
                    for p in self.prs
                    if p.get("merge_commit_sha") == path.split("/")[2]
                ]
            if path.startswith("/pulls/") and path.endswith("/files"):
                pr = self.prs[int(path.split("/")[2]) - 1]
                names = self.git(
                    "diff",
                    "--name-only",
                    text(obj(pr["base"])["sha"]),
                    text(obj(pr["head"])["sha"]),
                )
                return 200, [{"filename": name} for name in names.splitlines()]
            if path == "/actions/workflows/ci.yml/runs":
                return 200, {
                    "workflow_runs": [
                        r
                        for r in self.runs
                        if r["head_sha"] == query["head_sha"][0] and r["name"] == "CI"
                    ]
                }
            if path.startswith("/actions/runs/"):
                return 200, self.runs[int(path.rsplit("/", 1)[1]) - 1]
            if path == "/releases":
                return 200, self.releases
        if method == "POST":
            if path == "/git/trees":
                with tempfile.TemporaryDirectory() as directory:
                    env = {
                        **os.environ,
                        "GIT_INDEX_FILE": str(Path(directory) / "index"),
                    }
                    self.git("read-tree", text(data["base_tree"]), env=env)
                    changes = data["tree"]
                    assert isinstance(changes, list)
                    for change in changes:
                        file = obj(change)
                        blob = self.git(
                            "hash-object", "-w", "--stdin", input=text(file["content"])
                        )
                        self.git(
                            "update-index",
                            "--add",
                            "--cacheinfo",
                            "100644",
                            blob,
                            text(file["path"]),
                            env=env,
                        )
                    return 201, {"sha": self.git("write-tree", env=env)}
            if path == "/git/commits":
                parents = data["parents"]
                assert isinstance(parents, list)
                return 201, {
                    "sha": self.git(
                        "commit-tree",
                        text(data["tree"]),
                        "-p",
                        text(parents[0]),
                        "-m",
                        text(data["message"]),
                    )
                }
            if path == "/git/refs":
                ref = text(data["ref"])
                try:
                    self.git("rev-parse", "--verify", ref)
                except subprocess.CalledProcessError:
                    self.git("update-ref", ref, text(data["sha"]))
                    return 201, {"ref": ref}
                return 422, {"message": "Reference already exists"}
            if path == "/pulls":
                pr: Object = {
                    **data,
                    "number": len(self.prs) + 1,
                    "state": "open",
                    "merged_at": None,
                    "html_url": f"https://github.com/{REPOSITORY}/pull/{len(self.prs) + 1}",
                    "head": {
                        "ref": data["head"],
                        "sha": self.git("rev-parse", text(data["head"])),
                        "repo": {"full_name": REPOSITORY},
                    },
                    "base": {
                        "ref": data["base"],
                        "sha": self.git("rev-parse", text(data["base"])),
                    },
                }
                self.prs.append(pr)
                return 201, pr
            if path.startswith("/issues/") and path.endswith("/labels"):
                self.prs[int(path.split("/")[2]) - 1]["labels"] = data["labels"]
                return 200, data["labels"]
            if path.startswith("/issues/") and path.endswith("/comments"):
                pr = self.prs[int(path.split("/")[2]) - 1]
                comments = pr.setdefault("comments", [])
                assert isinstance(comments, list)
                comments.append(data["body"])
                return 201, data
            if path == "/releases":
                release: Object = {**data, "id": len(self.releases) + 1, "assets": []}
                self.releases.append(release)
                return 201, release
        if method == "PATCH" and path.startswith("/releases/"):
            release = self.releases[int(path.rsplit("/", 1)[1]) - 1]
            release.update(data)
            return 200, release
        if method == "PATCH" and path.startswith("/pulls/"):
            pr = self.prs[int(path.rsplit("/", 1)[1]) - 1]
            pr.update(data)
            return 200, pr
        if method == "DELETE" and path.startswith("/git/refs/heads/"):
            self.git("update-ref", "-d", "refs/" + path.removeprefix("/git/refs/"))
            return 204, None
        return 500, {"message": f"Unexpected API operation: {method} {path}"}


class ReleaseWorkflowTests(_RepoCase):
    def setUp(self) -> None:
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch.dict(os.environ, {"RELEASE_MANAGED": "true"}))
        self.history = {"version": "2.2.0", "date": "2026-10-07", "entries": [ENTRY]}
        self.root = self.make_repo(
            {"releases": [{"version": "2.4.0", "entries": [ENTRY]}, self.history]}
        )
        for name in [
            ".github/workflows/build_and_push_images.yml",
            "scripts/release_workflow.py",
            "scripts/check_whats_new.py",
            "scripts/release_notes.py",
            "scripts/release_bundle.py",
        ]:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / name, target)
        self.state = GitHubFixture(self.root)
        self.state.git("init", "-q", "-b", "release/v2.4")
        self.state.git("config", "user.name", "Release test")
        self.state.git("config", "user.email", "release-test@example.invalid")
        self.state.git("add", ".")
        self.state.git("commit", "-qm", "Release candidate")
        self.state.git("checkout", "-qb", "develop")
        future = {**copy.deepcopy(ENTRY), "id": "future-feature"}
        (self.root / NOTES).write_text(
            format_json(
                {
                    "releases": [
                        {"version": "next", "entries": [ENTRY, future]},
                        self.history,
                    ]
                }
            )
            + "\n"
        )
        self.state.git("add", ".")
        self.state.git("commit", "-qm", "Keep develop-only news")
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def handle_api(self) -> None:
                parsed = urlsplit(self.path)
                path = unquote(parsed.path.removeprefix("/repos/" + REPOSITORY))
                size = int(self.headers.get("Content-Length", "0"))
                data = obj(json.loads(self.rfile.read(size))) if size else {}
                status, response = state.request(
                    self.command, path, parse_qs(parsed.query), data
                )
                body = b"" if status == 204 else json.dumps(response).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = handle_api
            do_POST = handle_api
            do_PATCH = handle_api
            do_DELETE = handle_api

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.github = GitHub(
            REPOSITORY,
            "offline-test-token",
            f"http://127.0.0.1:{self.server.server_port}",
        )
        self.releases = Releases(self.root, self.github)
        self.version = Version("2.4.0")

    def stop_server(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def assert_ci_accepts_branch(self, pr: Object) -> None:
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
        step = workflow.split("- name: Check branch name\n", 1)[1].split(
            "\n      - name:", 1
        )[0]
        program = textwrap.dedent(step.split("        run: |\n", 1)[1])
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", program],
            env={**os.environ, "BRANCH_NAME": text(obj(pr["head"])["ref"])},
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def workflow_step(
        self, command: str, event_name: str, event: Object, managed: str = "true"
    ) -> subprocess.CompletedProcess[str]:
        """Run the real CLI with env from its workflow, job and selected step."""
        workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text()
        configuration, steps = workflow.split("\n    steps:\n", 1)
        step = next(
            block
            for block in steps.split("\n      - name:")
            if f"        run: python3 -m scripts.release_workflow {command}\n" in block
        )
        contexts = {
            "${{ vars.RELEASE_MANAGED }}": managed,
            "${{ inputs.version }}": self.version.value
            if event_name == "workflow_dispatch"
            else "",
            "${{ github.token }}": "offline-test-token",
            "${{ steps.app.outputs.token }}": "offline-test-token",
        }
        # Do not inherit the fixture's enabled flag: each process must receive
        # the same setting its actual Actions step declares.
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"RELEASE_MANAGED", "RELEASE_VERSION", "GH_TOKEN"}
        }
        event_path = self.root / "workflow-event.json"
        event_path.write_text(json.dumps(event))
        env.update(
            {
                "GITHUB_EVENT_PATH": str(event_path),
                "GITHUB_EVENT_NAME": event_name,
                "GITHUB_REPOSITORY": REPOSITORY,
                "GITHUB_REF": "refs/heads/develop",
                "GITHUB_OUTPUT": str(self.root / "workflow-output.txt"),
                "GITHUB_API_URL": f"http://127.0.0.1:{self.server.server_port}",
            }
        )
        for block, indent in [
            (configuration.split("\njobs:\n", 1)[0], 0),
            (configuration.split("\n  reconcile:\n", 1)[1], 4),
            (step, 8),
        ]:
            # These workflow env maps contain scalar values only. Read their
            # declarations without adding a YAML dependency to tooling tests.
            declaration = re.search(
                rf"(?m)^{' ' * indent}env:\n((?:{' ' * (indent + 2)}[A-Z_]+: [^\n]+\n)+)",
                block,
            )
            if declaration:
                for line in declaration[1].splitlines():
                    key, value = line.strip().split(": ", 1)
                    env[key] = contexts[value] if value.startswith("${{") else value
        return subprocess.run(
            [sys.executable, "-m", "scripts.release_workflow", command],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def prepared(self) -> tuple[Object, str]:
        self.releases.prepare(self.version)
        pr = self.state.prs[0]
        return pr, self.state.merge(pr)

    def built(self) -> tuple[str, Run]:
        _, sha = self.prepared()
        self.state.ci(sha)
        self.releases.tag(self.version, sha)
        release = self.state.releases[0]
        release["assets"] = [
            {"name": n}
            for n in [
                "release.json",
                "release.env",
                "SBOM-SHA256SUMS.txt",
                "IMAGE-DIGESTS.txt",
                "backend.cyclonedx.json",
            ]
        ]
        run = Run.from_event(
            {"workflow_run": self.state.ci(sha, "Build and Push Docker Images")},
            REPOSITORY,
        )
        assert run is not None
        return sha, run

    def offline_attestation(self, sha: str, failed: bool = False):
        directory = self.root / "bin"
        directory.mkdir(exist_ok=True)
        command = directory / "gh"
        command.write_text(
            "#!/usr/bin/env python3\n"
            "import json,os,sys\nfrom pathlib import Path\n"
            "if sys.argv[1:3] == ['release','download']:\n"
            " assert '--source-digest' not in sys.argv\n"
            " assets = json.loads(os.environ['TEST_ARTIFACTS'])\n"
            " assets['release.json'] = os.environ['TEST_BUNDLE']\n"
            " for i,arg in enumerate(sys.argv):\n"
            "  if arg == '--pattern':\n"
            "   name = sys.argv[i+1]\n"
            "   Path(sys.argv[sys.argv.index('--dir')+1], name).write_text(assets[name])\n"
            "else:\n"
            " assert sys.argv[1:3] == ['attestation','verify']\n"
            " assert sys.argv[sys.argv.index('--source-digest')+1] == os.environ['TEST_SOURCE_SHA']\n"
            " assert sys.argv[sys.argv.index('--source-ref')+1] == 'refs/tags/v2.4.0'\n"
            " workflow = 'build_and_push_images.yml' if Path(sys.argv[3]).name == 'release.json' else 'release_sbom.yml'\n"
            " assert sys.argv[sys.argv.index('--signer-workflow')+1] == 'eneo-ai/eneo/.github/workflows/' + workflow\n"
            " if os.environ.get('TEST_BAD_ATTESTATION') == '1':\n  sys.exit(1)\n"
        )
        command.chmod(0o755)
        recorded = bundle(
            self.version.value,
            sha,
            {c: REGISTRY + c + "@sha256:" + "a" * 64 for c in COMPONENTS},
        )
        assets = {
            "IMAGE-DIGESTS.txt": "backend sha256:" + "a" * 64,
            "backend.cyclonedx.json": '{"bomFormat":"CycloneDX"}\n',
        }
        sums = "".join(
            hashlib.sha256(content.encode()).hexdigest() + "  " + name + "\n"
            for name, content in assets.items()
        )
        assets["SBOM-SHA256SUMS.txt"] = sums
        assets["release.env"] = environment(
            self.version.value,
            sha,
            {c: REGISTRY + c + "@sha256:" + "a" * 64 for c in COMPONENTS},
        )
        return patch.dict(
            os.environ,
            {
                "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                "TEST_BUNDLE": json.dumps(recorded),
                "TEST_SOURCE_SHA": sha,
                "TEST_ARTIFACTS": json.dumps(assets),
                "TEST_BAD_ATTESTATION": "1" if failed else "0",
            },
        )

    def test_prepare_dates_once_reuses_the_pr_and_does_not_tag(self) -> None:
        self.releases.prepare(self.version)
        pr = self.state.prs[0]
        self.assert_ci_accepts_branch(pr)
        first = copy.deepcopy(pr)
        candidate = text(obj(pr["head"])["sha"])
        notes = json.loads(self.state.git("show", candidate + ":" + NOTES))
        self.assertEqual(
            notes["releases"][0]["date"], datetime.date.today().isoformat()
        )
        self.assertEqual(request_at(self.root, candidate).version, self.version)
        self.releases.prepare(self.version)
        self.assertEqual(self.state.prs, [first])
        self.assertIsNone(self.github.tag_sha(self.version))
        self.assertEqual(self.state.releases, [])

    def test_workflow_dispatch_prepares_with_its_declared_environment(self) -> None:
        result = self.workflow_step("plan", "workflow_dispatch", {})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Release operation: prepare", result.stdout)
        result = self.workflow_step("run", "workflow_dispatch", {})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.state.prs), 1)
        candidate = text(obj(self.state.prs[0]["head"])["sha"])
        self.assertEqual(request_at(self.root, candidate).version, self.version)
        self.assertIsNone(self.github.tag_sha(self.version))

    def test_ci_workflow_step_tags_the_reviewed_commit(self) -> None:
        _, sha = self.prepared()
        event = {"workflow_run": self.state.ci(sha)}
        result = self.workflow_step("plan", "workflow_run", event)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Release operation: tag", result.stdout)
        result = self.workflow_step("run", "workflow_run", event)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.github.tag_sha(self.version), sha)
        self.assertTrue(self.state.releases[0]["draft"])

    def test_image_workflow_steps_publish_and_port_release_history(self) -> None:
        sha, _ = self.built()
        event = {"workflow_run": self.state.runs[-1]}
        with self.offline_attestation(sha):
            result = self.workflow_step("plan", "workflow_run", event)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Release operation: complete", result.stdout)
            result = self.workflow_step("run", "workflow_run", event)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(self.state.releases[0]["draft"])
            result = self.workflow_step("port", "workflow_run", event)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.state.prs), 2)
        self.assertEqual(obj(self.state.prs[1]["base"])["ref"], "develop")

    def test_workflow_steps_keep_managed_publication_disabled(self) -> None:
        for managed in ["", "false"]:
            for command in ["plan", "run"]:
                with self.subTest(managed=managed, command=command):
                    result = self.workflow_step(
                        command, "workflow_dispatch", {}, managed
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Managed publication is off", result.stderr)
            sha = self.state.git("rev-parse", "release/v2.4")
            event = {"workflow_run": self.state.ci(sha)}
            for command in ["run", "port"]:
                with self.subTest(managed=managed, command=command):
                    result = self.workflow_step(command, "workflow_run", event, managed)
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
        self.assertEqual(self.state.prs, [])
        self.assertEqual(self.state.releases, [])

    def test_resume_after_branch_creation_preserves_the_same_candidate(self) -> None:
        request = ReleaseRequest(
            self.version, self.state.git("rev-parse", self.version.branch)
        )
        self.state.fail = ("POST", "/pulls")
        with self.assertRaises(HTTPError):
            self.releases.prepare(self.version)
        original = self.state.git("rev-parse", request.branch)
        self.releases.prepare(self.version)
        self.assertEqual(obj(self.state.prs[0]["head"])["sha"], original)

    def test_a_fresh_job_fetches_candidate_commits_created_after_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "job"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    str(self.root),
                    str(clone),
                ],
                check=True,
            )
            controller = Releases(clone, self.github)
            controller.prepare(self.version)
            controller.prepare(self.version)
            self.assertEqual(len(self.state.prs), 1)
            candidate = text(obj(self.state.prs[0]["head"])["sha"])
            self.assertEqual(request_at(clone, candidate).version, self.version)

    def test_tag_waits_for_merged_commit_ci_and_keeps_the_release_draft(self) -> None:
        _, sha = self.prepared()
        self.state.ci(sha, conclusion="failure")
        self.releases.tag(self.version, sha)
        self.assertIsNone(self.github.tag_sha(self.version))
        self.state.ci(sha)
        self.releases.tag(self.version, sha)
        self.releases.prepare(self.version)
        self.assertEqual(self.github.tag_sha(self.version), sha)
        self.assertEqual(len(self.state.releases), 1)
        self.assertTrue(self.state.releases[0]["draft"])
        self.assertEqual(self.state.releases[0]["target_commitish"], sha)

    def test_resume_after_draft_creation_does_not_duplicate_or_replace_it(self) -> None:
        _, sha = self.prepared()
        self.state.ci(sha)
        self.state.fail = ("POST", "/git/refs")
        with self.assertRaises(HTTPError):
            self.releases.tag(self.version, sha)
        self.assertTrue(self.state.releases[0]["draft"])
        self.assertIsNone(self.github.tag_sha(self.version))
        self.releases.prepare(self.version)
        self.assertEqual(len(self.state.releases), 1)
        self.assertEqual(self.github.tag_sha(self.version), sha)

    def test_new_commits_need_a_new_reviewed_request(self) -> None:
        _, sha = self.prepared()
        self.state.ci(sha)
        tree = self.state.git("rev-parse", sha + "^{tree}")
        advanced = self.state.git(
            "commit-tree", tree, "-p", sha, "-m", "Additional fix"
        )
        self.state.git("update-ref", "refs/heads/release/v2.4", advanced)
        with self.assertRaisesRegex(ReleaseError, "advanced"):
            self.releases.tag(self.version, sha)
        self.releases.prepare(self.version)
        self.assertEqual(len(self.state.prs), 2)
        self.assertNotEqual(
            obj(self.state.prs[0]["head"])["ref"], obj(self.state.prs[1]["head"])["ref"]
        )
        event = {"workflow_run": self.state.ci(advanced)}
        self.assertEqual(
            plan(self.root, event, "workflow_run", REPOSITORY, "")[0], "skip"
        )

    def test_a_newer_base_closes_the_stale_preparation_pr(self) -> None:
        self.releases.prepare(self.version)
        stale = self.state.prs[0]
        tree = self.state.git("rev-parse", "release/v2.4^{tree}")
        advanced = self.state.git(
            "commit-tree",
            tree,
            "-p",
            self.state.git("rev-parse", "release/v2.4"),
            "-m",
            "Additional fix",
        )
        self.state.git("update-ref", "refs/heads/release/v2.4", advanced)
        self.releases.prepare(self.version)
        current = self.state.prs[1]
        self.assertEqual(stale["state"], "closed")
        self.assertIsNone(stale["merged_at"])
        self.assertEqual(current["state"], "open")
        comments = stale["comments"]
        assert isinstance(comments, list)
        self.assertIn(text(current["html_url"]), text(comments[0]))
        self.assertEqual(
            request_at(self.root, text(obj(current["head"])["sha"])).base_sha, advanced
        )
        # The replacement is idempotent and never touches the current PR.
        self.releases.prepare(self.version)
        self.assertEqual(len(self.state.prs), 2)
        self.assertEqual(current["state"], "open")
        self.assertNotIn("comments", current)

    def test_managed_publication_is_off_until_the_repository_variable_is_set(
        self,
    ) -> None:
        head = self.state.git("rev-parse", "release/v2.4")
        with patch.dict(os.environ, {"RELEASE_MANAGED": "true"}):
            with self.assertRaisesRegex(ReleaseError, "reviewed release request"):
                identify(self.root, "refs/tags/v2.4.0", head)
        for value in ["", "false", "yes"]:
            with patch.dict(os.environ, {"RELEASE_MANAGED": value}):
                self.assertFalse(identify(self.root, "refs/tags/v2.4.0", head))
        with patch.dict(os.environ, {"RELEASE_MANAGED": " TRUE "}):
            with self.assertRaisesRegex(ReleaseError, "reviewed release request"):
                identify(self.root, "refs/tags/v2.4.0", head)
        os.environ.pop("RELEASE_MANAGED")
        self.assertFalse(identify(self.root, "refs/tags/v2.4.0", head))
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/develop"}):
            with self.assertRaisesRegex(ReleaseError, "RELEASE_MANAGED=true"):
                plan(self.root, {}, "workflow_dispatch", REPOSITORY, "2.4.0")
        with patch.dict(os.environ, {"RELEASE_MANAGED": "true"}):
            _, sha = self.prepared()
        event = {"workflow_run": self.state.ci(sha)}
        self.assertEqual(
            plan(self.root, event, "workflow_run", REPOSITORY, "")[0], "skip"
        )
        with patch.dict(os.environ, {"RELEASE_MANAGED": "true"}):
            self.assertEqual(
                plan(self.root, event, "workflow_run", REPOSITORY, "")[0], "tag"
            )

    def test_shared_release_note_rules_must_match_develop(self) -> None:
        for path in [
            "frontend/packages/whats-new/releases.schema.json",
            "scripts/check_whats_new.py",
        ]:
            with self.subTest(path=path):
                self.state.git("checkout", "-q", "release/v2.4")
                target = self.root / path
                target.write_bytes(target.read_bytes() + b"\n")
                self.state.git("add", ".")
                self.state.git("commit", "-qm", "Diverged rules")
                self.state.git("checkout", "-q", "develop")
                with self.assertRaisesRegex(ReleaseError, "differs from develop"):
                    self.releases.prepare(self.version)
                self.assertEqual(self.state.prs, [])

    def test_an_interrupted_port_branch_is_replaced_when_develop_moved_on(
        self,
    ) -> None:
        sha, run = self.built()
        with self.offline_attestation(sha):
            self.releases.complete(self.version, run)
        self.state.fail = ("POST", "/pulls")
        with self.assertRaises(HTTPError):
            self.releases.port(self.version, sha)
        interrupted = self.state.git("rev-parse", "refs/heads/docs/port-v2.4.0")
        data = json.loads((self.root / NOTES).read_text())
        data["releases"][0]["entries"].append(
            {**copy.deepcopy(ENTRY), "id": "later-feature"}
        )
        (self.root / NOTES).write_text(format_json(data) + "\n")
        self.state.git("add", ".")
        self.state.git("commit", "-qm", "More upcoming news")
        self.releases.port(self.version, sha)
        port_pr = self.state.prs[1]
        self.assertNotEqual(obj(port_pr["head"])["sha"], interrupted)
        notes = json.loads(
            self.state.git("show", text(obj(port_pr["head"])["sha"]) + ":" + NOTES)
        )["releases"]
        self.assertEqual(
            [e["id"] for e in notes[0]["entries"]], ["future-feature", "later-feature"]
        )
        self.assertEqual(notes[1]["version"], "2.4.0")

    def test_moved_tags_are_never_replaced(self) -> None:
        _, sha = self.prepared()
        self.state.ci(sha)
        other = self.state.git("rev-parse", "develop")
        self.state.git("update-ref", "refs/tags/v2.4.0", other)
        with self.assertRaisesRegex(ReleaseError, "refusing to move"):
            self.releases.tag(self.version, sha)
        self.assertEqual(self.github.tag_sha(self.version), other)

    def test_no_publication_before_complete_assets_or_valid_attestation(self) -> None:
        sha, run = self.built()
        assets = self.state.releases[0]["assets"]
        self.state.releases[0]["assets"] = []
        with self.assertRaisesRegex(ReleaseError, "incomplete"):
            self.releases.complete(self.version, run)
        self.state.releases[0]["assets"] = assets
        with self.offline_attestation(sha, failed=True):
            with self.assertRaises(subprocess.CalledProcessError):
                self.releases.complete(self.version, run)
        self.assertTrue(self.state.releases[0]["draft"])

    def test_publication_and_port_are_retryable_and_keep_future_news(self) -> None:
        sha, run = self.built()
        with self.offline_attestation(sha):
            self.releases.complete(self.version, run)
            self.releases.complete(self.version, run)
        self.assertFalse(self.state.releases[0]["draft"])
        self.releases.port(self.version, sha)
        self.releases.port(self.version, sha)
        self.assertEqual(len(self.state.prs), 2)
        port_pr = self.state.prs[1]
        self.assert_ci_accepts_branch(port_pr)
        notes = json.loads(
            self.state.git("show", text(obj(port_pr["head"])["sha"]) + ":" + NOTES)
        )["releases"]
        self.assertEqual([e["id"] for e in notes[0]["entries"]], ["future-feature"])
        self.assertEqual(notes[1]["version"], "2.4.0")
        self.assertEqual(notes[1]["entries"], [ENTRY])
        self.state.merge(port_pr)
        self.releases.port(self.version, sha)
        self.assertEqual(len(self.state.prs), 2)

    def test_foreign_pr_and_failed_workflows_cannot_plan_a_transition(self) -> None:
        _, sha = self.prepared()
        for change in [
            {"event": "pull_request"},
            {"conclusion": "failure"},
            {"head_repository": {"full_name": "someone/eneo"}},
            {"path": ".github/workflows/unrelated.yml"},
        ]:
            event = {"workflow_run": {**self.state.ci(sha), **change}}
            self.assertEqual(
                plan(self.root, event, "workflow_run", REPOSITORY, "")[0], "skip"
            )

    def test_new_final_tags_require_a_request_while_rc_and_develop_are_unchanged(
        self,
    ) -> None:
        with self.assertRaisesRegex(ReleaseError, "matching reviewed release request"):
            managed_tag("refs/tags/v2.4.0", None)
        self.assertFalse(managed_tag("refs/heads/develop", None))
        self.assertFalse(managed_tag("refs/tags/v2.4.0-rc.1", None))
        _, sha = self.prepared()
        request = request_at(self.root, sha)
        self.assertTrue(managed_tag("refs/tags/v2.4.0", request))
        self.assertFalse(managed_tag("refs/tags/v2.4.1-rc.1", request))
        with self.assertRaisesRegex(ReleaseError, "matching reviewed release request"):
            managed_tag("refs/tags/v2.4.1", request)

    def test_invalid_versions_and_notes_cannot_create_a_pr(self) -> None:
        for value in ["2.4.0-rc.1", "v2.4.0", "02.4.0", "2.4", "2.4.0\n"]:
            with self.assertRaises(ReleaseError):
                Version(value)
        self.state.git("checkout", "-q", "release/v2.4")
        data = json.loads((self.root / NOTES).read_text())
        del data["releases"][0]["entries"][0]["title"]
        (self.root / NOTES).write_text(format_json(data) + "\n")
        self.state.git("add", ".")
        self.state.git("commit", "-qm", "Invalid candidate notes")
        self.state.git("checkout", "-q", "develop")
        with self.assertRaisesRegex(ReleaseError, "final validation"):
            self.releases.prepare(self.version)
        self.assertEqual(self.state.prs, [])
        self.assertEqual(self.state.releases, [])

    def test_hotfix_without_notes_still_gets_a_reviewable_request(self) -> None:
        version = Version("2.4.1")
        self.state.git("checkout", "-q", "release/v2.4")
        data = json.loads((self.root / NOTES).read_text())
        data["releases"][0]["date"] = "2026-11-01"
        (self.root / NOTES).write_text(format_json(data) + "\n")
        self.state.git("add", ".")
        self.state.git("commit", "-qm", "Previous dated release")
        self.state.git("checkout", "-q", "develop")
        self.releases.prepare(version)
        candidate = text(obj(self.state.prs[0]["head"])["sha"])
        self.assertEqual(request_at(self.root, candidate).version, version)
        self.assertEqual(
            json.loads(self.state.git("show", candidate + ":" + NOTES))["releases"],
            data["releases"],
        )

    def test_old_release_coordinators_must_be_backported_before_preparation(
        self,
    ) -> None:
        self.state.git("checkout", "-q", "release/v2.4")
        (self.root / "scripts/release_workflow.py").unlink()
        self.state.git("add", ".")
        self.state.git("commit", "-qm", "Before managed publication")
        self.state.git("checkout", "-q", "develop")
        with self.assertRaisesRegex(ReleaseError, "predates managed publication"):
            self.releases.prepare(self.version)
        self.assertEqual(self.state.prs, [])

    def test_successful_workflow_cannot_publish_a_bundle_for_another_commit(
        self,
    ) -> None:
        sha, run = self.built()
        with self.offline_attestation(sha):
            with patch.dict(
                os.environ,
                {
                    "TEST_BUNDLE": json.dumps(
                        bundle(
                            self.version.value,
                            "b" * 40,
                            {
                                c: REGISTRY + c + "@sha256:" + "a" * 64
                                for c in COMPONENTS
                            },
                        )
                    )
                },
            ):
                with self.assertRaisesRegex(
                    ReleaseError, "different version or source"
                ):
                    self.releases.complete(self.version, run)
        self.assertTrue(self.state.releases[0]["draft"])

    def test_a_newer_unfinished_tag_does_not_block_a_completed_release(self) -> None:
        sha, run = self.built()
        self.state.git("update-ref", "refs/tags/v2.5.0", sha)
        self.state.releases.append(
            {"id": 2, "tag_name": "v2.5.0", "draft": True, "prerelease": False}
        )
        with self.offline_attestation(sha):
            self.releases.complete(self.version, run)
        self.assertEqual(self.state.releases[0]["make_latest"], "true")

    def test_an_older_supported_line_does_not_replace_latest(self) -> None:
        sha, run = self.built()
        self.state.releases.append(
            {"id": 2, "tag_name": "v2.5.0", "draft": False, "prerelease": False}
        )
        with self.offline_attestation(sha):
            self.releases.complete(self.version, run)
        self.assertEqual(self.state.releases[0]["make_latest"], "false")

    def test_annotated_release_tags_are_resolved_to_the_same_source_commit(
        self,
    ) -> None:
        _, sha = self.prepared()
        self.state.ci(sha)
        self.state.git("tag", "-a", "v2.4.0", sha, "-m", "Same immutable release")
        self.releases.tag(self.version, sha)
        self.assertEqual(self.github.tag_sha(self.version), sha)

    def test_only_the_preparation_merge_plans_tagging(self) -> None:
        _, sha = self.prepared()
        operation, version, run = plan(
            self.root,
            {"workflow_run": self.state.ci(sha)},
            "workflow_run",
            REPOSITORY,
            "",
        )
        self.assertEqual(operation, "tag")
        self.assertEqual(version, self.version)
        assert run is not None
        self.assertEqual(run.sha, sha)

    def test_changed_environment_or_sbom_bytes_keep_the_release_draft(self) -> None:
        sha, run = self.built()
        for name, message in [
            ("release.env", "deployment environment"),
            ("backend.cyclonedx.json", "attested checksum"),
        ]:
            with self.subTest(name=name), self.offline_attestation(sha):
                assets = json.loads(os.environ["TEST_ARTIFACTS"])
                assets[name] = "Changed after the build"
                with patch.dict(os.environ, {"TEST_ARTIFACTS": json.dumps(assets)}):
                    with self.assertRaisesRegex(ReleaseError, message):
                        self.releases.complete(self.version, run)
            self.assertTrue(self.state.releases[0]["draft"])
