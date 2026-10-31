import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { checkBuildMemory, readPeakRssMb } from "./ci-build-memory.mjs";
import { changedFiles, planCi } from "./ci-change-scope.mjs";
import { evaluateCi } from "./ci-gate.mjs";

const root = fileURLToPath(new URL("../../", import.meta.url));
const appFile = "frontend/apps/web/src/routes/+page.svelte";
const backendFile = "backend/src/eneo/server/main.py";
const docsFile = "frontend/apps/docs-site/src/content/contributing/index.mdx";
const resultsFor = (plan) => Object.fromEntries(Object.entries(plan.expected_jobs)
  .map(([job, required]) => [job, { result: required ? "success" : "skipped" }]));

for (const event of ["pull_request", "merge_group"]) {
  test(`${event}: Svelte-only changes retain E2E and a production image build`, () => {
    const plan = planCi([appFile], event);
    assert.equal(plan.frontend, true);
    assert.equal(plan.frontend_e2e, true);
    assert.equal(plan.backend, false);
    assert.equal(plan.web_next, false);
    assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["frontend"]);
    assert.deepEqual(evaluateCi(plan.expected_jobs, resultsFor(plan)), []);
  });

  test(`${event}: backend changes test both API consumers without unrelated image builds`, () => {
    const plan = planCi([backendFile], event);
    assert.equal(plan.backend, true);
    assert.equal(plan.schema, true);
    assert.equal(plan.frontend_e2e, true);
    assert.equal(plan.web_next_e2e, true);
    assert.equal(plan.web_next, false);
    assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["backend"]);
  });

  test(`${event}: docs-only changes create no Docker runners and still require security`, () => {
    const plan = planCi([docsFile], event);
    assert.equal(plan.docker, false);
    assert.deepEqual(plan.docker_matrix, { include: [] });
    assert.equal(plan.expected_jobs.security, true);
    assert.deepEqual(evaluateCi(plan.expected_jobs, resultsFor(plan)), []);
  });
}

test("shared frontend inputs validate both apps and all application images", () => {
  for (const file of ["frontend/bun.lock", "frontend/package.json", "frontend/patches/x.patch", "frontend/packages/ui/src/styles/main.css"]) {
    const plan = planCi([file], "merge_group");
    for (const name of ["frontend", "frontend_e2e", "web_next", "web_next_e2e"]) assert.equal(plan[name], true, `${file}: ${name}`);
    assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["backend", "frontend"]);
  }
});

test("workflow, local action, scope and gate changes force full validation", () => {
  for (const file of [".github/workflows/ci.yml", ".github/actions/setup-playwright/action.yml", ".github/scripts/ci-gate.mjs"]) {
    const plan = planCi([file], "merge_group");
    assert.equal(plan.full, true);
    assert.equal(plan.docker_matrix.include.length, 3);
  }
});

test("only the job limit bounds Playwright system libraries from a slow mirror", () => {
  const action = fs.readFileSync(path.join(root, ".github/actions/setup-playwright/action.yml"), "utf8");
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  // Slow mirrors that kept progressing needed about 590 s (develop run 40352666820)
  // and more than 720 s (run 40367572604); a step deadline turns them red.
  const step = action.split("- name: Install system libraries\n")[1]?.split(/\n    - name: /)[0];
  const install = step?.split("\n").find((line) => line.includes("playwright install-deps"));
  assert.equal(install?.trim(), "bun run --bun playwright install-deps chromium");
  assert.doesNotMatch(step, /^      timeout-minutes:/m);
  const jobs = workflow.split("\njobs:\n")[1].split(/\n(?=  [a-z][a-z0-9-]*:\n)/)
    .filter((block) => block.includes("uses: ./.github/actions/setup-playwright"));
  assert.ok(jobs.length > 0);
  for (const block of jobs) {
    const limit = Number(block.match(/^    timeout-minutes: (\d+)$/m)?.[1]);
    assert.ok(limit >= 30, `${block.match(/^  ([a-z0-9-]+):/)[1]}: ${limit} min`);
  }
});

test("the Svelte build is checked against a memory budget below its heap limit", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const stepBody = (name) => workflow.split(`- name: ${name}\n`)[1]?.split(/\n      - name: /)[0];
  const build = stepBody("Build web app for E2E");
  const check = stepBody("Check build memory budget");
  const heapMb = Number(build?.match(/--max-old-space-size=(\d+)/)?.[1]);
  const budgetMb = Number(check?.match(/BUILD_MEMORY_BUDGET_MB: "(\d+)"/)?.[1]);
  assert.ok(budgetMb > 0 && budgetMb < heapMb, `budget ${budgetMb} MB, heap ${heapMb} MB`);
  const report = build.match(/\/usr\/bin\/time -v -o "([^"]+)"/)?.[1];
  assert.ok(report && check.includes(`node .github/scripts/ci-build-memory.mjs "${report}"`));
  assert.ok(workflow.indexOf("- name: Check build memory budget") > workflow.indexOf("- name: Build web app for E2E"));
});

test("web-next runs all browser cases on FastAPI and has no Next runtime job", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const job = workflow.split("\n  frontend-web-next-e2e:\n")[1].split("\n  schema-drift:\n")[0];
  assert.doesNotMatch(job, /next start|next-web-next|SESSION_SECRET|--grep|\.next\/cache/);
  const native = job.split("- name: Run E2E and accessibility tests\n")[1]?.split(/\n      - name: /)[0];
  assert.match(native ?? "", /E2E_BASE_URL: http:\/\/localhost:8124/);
  assert.match(native ?? "", /^        run: bun run test:e2e$/m);
  const assets = job.indexOf("- name: Build browser asset map");
  assert.ok(assets > 0 && assets < job.indexOf("- name: Run E2E and accessibility tests"));
  assert.match(job.slice(assets), /run: bun run --filter '@eneo\/web-next' build/);
});

test("web-next rejects route drift and retains Vite resource reports after build failure", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const job = workflow.split("\n  frontend-web-next:\n")[1].split("\n  frontend-e2e:\n")[0];
  const step = (name) => job.split(`- name: ${name}\n`)[1]?.split(/\n      - name: /)[0];
  assert.match(job, /working-directory: frontend\n/);
  assert.match(job, /fetch-depth: 0/);
  assert.match(job, /ROUTE_PARITY_UPSTREAM:/);
  assert.match(step("Check route tree drift") ?? "", /routes:generate && git diff --exit-code -- apps\/web-next\/src\/routeTree\.gen\.ts/);
  assert.ok(job.indexOf("- name: Check route tree drift") < job.indexOf("- name: Type check"));
  const report = "$RUNNER_TEMP/web-next-vite-build.txt";
  assert.ok(step("Build (Vite)")?.includes(`/usr/bin/time -v -o "${report}" bun run --filter '@eneo/web-next' build`));
  assert.ok(step("Record Vite build memory")?.includes("Maximum resident set size"));
  for (const name of ["Record Vite build memory", "Upload Vite build reports"]) {
    assert.ok(step(name)?.includes("if: ${{ !cancelled() }}"), name);
  }
  const upload = step("Upload Vite build reports");
  assert.ok(upload?.includes("name: web-next-vite-build-resources"));
  assert.ok(upload.includes("${{ runner.temp }}/web-next-vite-build.txt"));
  assert.ok(upload.includes("frontend/apps/web-next/node_modules/.cache/vite-bundle-report.json"));
  assert.ok(upload.includes("include-hidden-files: true"), "the explicitly selected .cache report is uploaded");
  assert.ok(upload.includes("retention-days: 7") && upload.includes("if-no-files-found: ignore"));
  assert.ok(!job.includes("ci-build-memory.mjs"), "Vite sizes and RSS are report-only");
});

test("the memory check passes within budget and fails above it or without a measurement", () => {
  const report = (kb) => `\tCommand being timed: "bun run build"\n\tMaximum resident set size (kbytes): ${kb}\n\tExit status: 0\n`;
  assert.equal(readPeakRssMb(report(6_291_456)), 6144);
  assert.equal(checkBuildMemory(6144, 7680).ok, true);
  assert.equal(checkBuildMemory(7681, 7680).ok, false);
  assert.throws(() => readPeakRssMb("\tExit status: 0\n"));
  assert.throws(() => checkBuildMemory(6144, Number(undefined)));

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "eneo-ci-memory-"));
  try {
    const summary = path.join(dir, "summary.md");
    const run = (file) => spawnSync(process.execPath, [path.join(root, ".github/scripts/ci-build-memory.mjs"), file], {
      encoding: "utf8", timeout: 5_000,
      env: { ...process.env, BUILD_MEMORY_BUDGET_MB: "7680", GITHUB_STEP_SUMMARY: summary },
    });
    const within = path.join(dir, "within.txt");
    const over = path.join(dir, "over.txt");
    fs.writeFileSync(within, report(6_291_456));
    // A successful build of 2026-10-26 that was close to crashing.
    fs.writeFileSync(over, report(9_752_000));
    assert.equal(run(within).status, 0);
    assert.match(fs.readFileSync(summary, "utf8"), /peak 6\.00 GB of a 7\.50 GB budget/);
    const failed = run(over);
    assert.equal(failed.status, 1);
    assert.match(failed.stderr, /::error::Svelte production build: peak 9\.30 GB/);
    assert.equal(run(path.join(dir, "missing.txt")).status, 1);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("ci.yml can be run by hand on an integration branch", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  assert.ok(workflow.split("\njobs:\n")[0].includes("\n  workflow_dispatch:\n"));
});

test("push, tag and manual callers keep full validation even with only docs changed", () => {
  for (const event of ["push", "workflow_dispatch", "workflow_call", "unknown"]) {
    const plan = planCi([docsFile], event);
    assert.equal(plan.full, true);
    assert.equal(plan.docker_matrix.include.length, 3);
    assert.equal(plan.expected_jobs["user-facing"], false);
  }
});

test("a combined candidate includes requirements from every changed area", () => {
  const plan = planCi([backendFile, appFile], "merge_group");
  assert.equal(plan.backend, true);
  assert.equal(plan.frontend, true);
  assert.equal(plan.web_next_e2e, true);
  assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["backend", "frontend"]);
});

test("empty diffs run the full suite", () => {
  assert.equal(planCi([], "merge_group").full, true);
});

test("unmapped runtime and root configuration paths run the full suite", () => {
  for (const file of ["new-service/main.py", ".env.example", "docker-compose.yml"]) {
    assert.equal(planCi([file], "merge_group").full, true, file);
  }
});

test("contract inputs select their consumers and developer tooling", () => {
  const cases = [
    ["backend/src/eneo/roles/permissions.py", ["backend", "scripts", "route_metadata"]],
    ["scripts/backend_test_shard.py", ["backend", "scripts"]],
    ["scripts/check_whats_new.py", ["frontend", "scripts"]],
    ["frontend/packages/whats-new/version-order.cases.json", ["backend", "frontend", "scripts"]],
    ["frontend/apps/web-next/src/lib/auth/safe-next.cases.json", ["backend", "web_next", "web_next_e2e"]],
    ["frontend/packages/whats-new/releases.schema.json", ["backend", "frontend", "scripts"]],
    ["frontend/packages/eneo-js/src/types/schema.d.ts", ["schema", "frontend", "web_next"]],
    [".github/scripts/project-intake.mjs", ["scripts"]],
    ["e2e/mock_model_server.py", ["frontend_e2e", "web_next_e2e"]],
    [".devcontainer/Dockerfile", ["docker_devcontainer"]],
  ];
  for (const [file, required] of cases) {
    const plan = planCi([file], "merge_group");
    for (const name of required) assert.equal(plan[name], true, `${file}: ${name}`);
  }
  assert.equal(planCi([backendFile], "pull_request").scripts, false);
});

test("web-next-only changes do not build the Svelte app", () => {
  const plan = planCi(["frontend/apps/web-next/src/routes/index.tsx"], "merge_group");
  assert.equal(plan.web_next, true);
  assert.equal(plan.web_next_e2e, true);
  assert.equal(plan.frontend, false);
  assert.equal(plan.frontend_e2e, false);
  assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["backend"]);
});

test("web-next inputs rebuild the backend image that bundles the web app", () => {
  for (const file of ["frontend/bunfig.toml", "frontend/apps/web-next/src/main.tsx"]) {
    const plan = planCi([file], "merge_group");
    const backend = plan.docker_matrix.include.find(({ image }) => image === "backend");
    assert.equal(backend?.build_contexts, "web=./frontend", file);
  }
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  assert.match(workflow, /build-contexts: \$\{\{ matrix\.build_contexts \}\}/);
});

test("missing, failed, cancelled and unexpectedly skipped required jobs fail the gate", () => {
  const plan = planCi([appFile], "merge_group");
  for (const job of Object.keys(plan.expected_jobs).filter((job) => plan.expected_jobs[job])) {
    for (const result of ["failure", "cancelled", "skipped", "timed_out", undefined]) {
      const needs = resultsFor(plan);
      needs[job] = result ? { result } : undefined;
      assert.ok(evaluateCi(plan.expected_jobs, needs).some((error) => error.startsWith(`${job}:`)), `${job}: ${result}`);
    }
  }
});

test("optional jobs cannot hide a failure and unknown jobs cannot bypass the gate", () => {
  const plan = planCi([docsFile], "merge_group");
  const needs = resultsFor(plan);
  needs.frontend.result = "failure";
  assert.ok(evaluateCi(plan.expected_jobs, needs).length);
  needs.frontend.result = "skipped";
  needs.new_job = { result: "success" };
  assert.ok(evaluateCi(plan.expected_jobs, needs).some((error) => error.startsWith("new_job:")));
  assert.ok(evaluateCi({}, {}).length);
  assert.throws(() => evaluateCi(null, needs));
});

test("a broken scope job cannot turn the aggregate green", () => {
  const plan = planCi([docsFile], "merge_group");
  const needs = resultsFor(plan);
  needs.changes.result = "failure";
  assert.ok(evaluateCi(plan.expected_jobs, needs).length);
  const run = spawnSync(process.execPath, [path.join(root, ".github/scripts/ci-gate.mjs")], {
    env: { ...process.env, EXPECTED_JOBS: "", JOB_RESULTS: JSON.stringify(needs) }, timeout: 5_000,
  });
  assert.equal(run.status, 1);
});

test("every worker in ci.yml is included in the scope plan and aggregate needs", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const jobs = [...workflow.slice(workflow.indexOf("\njobs:")).matchAll(/^  ([a-z][a-z0-9-]*):$/gm)].map((match) => match[1]);
  const workers = jobs.filter((job) => job !== "ci").sort();
  assert.deepEqual(Object.keys(planCi([], "push").expected_jobs).sort(), workers);
  const aggregate = workflow.slice(workflow.indexOf("\n  ci:"));
  const needs = aggregate.slice(aggregate.indexOf("    needs:"), aggregate.indexOf("    steps:"));
  assert.deepEqual([...needs.matchAll(/^      - ([a-z0-9-]+)$/gm)].map((match) => match[1]).sort(), workers);
});

test("workflow selection matches the required-job plan for each kind of change", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  for (const event of ["pull_request", "merge_group", "push", "workflow_dispatch"]) {
    for (const files of [[appFile], [backendFile], [docsFile], ["frontend/bun.lock"], [appFile, backendFile], []]) {
      const plan = planCi(files, event);
      for (const [job, required] of Object.entries(plan.expected_jobs)) {
        if (["changes", "security", "user-facing"].includes(job)) continue;
        const block = workflow.split(`\n  ${job}:\n`)[1]?.split(/\n  [a-z][a-z0-9-]*:\n/)[0];
        const condition = block?.match(/^    if: needs\.changes\.outputs\.([a-z0-9_]+) == 'true'$/m);
        assert.ok(condition, `${job} must use the canonical scope output`);
        assert.equal(plan[condition[1]], required, `${event}, ${files}: ${job}`);
      }
    }
  }
});

test("each candidate is classified by its own diff onto the preceding candidate, and a bad base runs everything", () => {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "eneo-ci-diff-"));
  const git = (...args) => execFileSync("git", args, {
    cwd, encoding: "utf8", timeout: 5_000,
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null" },
  }).trim();
  const write = (file, content) => {
    fs.mkdirSync(path.dirname(path.join(cwd, file)), { recursive: true });
    fs.writeFileSync(path.join(cwd, file), content);
  };
  try {
    git("init", "--quiet");
    git("config", "user.name", "CI contract test");
    git("config", "user.email", "ci@example.invalid");
    const scope = (baseSha, head) => {
      const eventPath = path.join(cwd, "event.json");
      fs.writeFileSync(eventPath, JSON.stringify({ merge_group: { base_sha: baseSha } }));
      return spawnSync(process.execPath, [path.join(root, ".github/scripts/ci-change-scope.mjs"), "--github-event"], {
        cwd, encoding: "utf8", timeout: 5_000,
        env: { ...process.env, GITHUB_EVENT_NAME: "merge_group", GITHUB_EVENT_PATH: eventPath, GITHUB_SHA: head, GITHUB_STEP_SUMMARY: "" },
      });
    };
    write(backendFile, "original\n");
    git("add", "."); git("commit", "--quiet", "-m", "develop");
    write(backendFile, "earlier queued PR\n");
    git("add", "."); git("commit", "--quiet", "-m", "preceding candidate");
    const preceding = git("rev-parse", "HEAD");
    write(appFile, "later queued PR\n");
    git("add", "."); git("commit", "--quiet", "-m", "candidate");
    let head = git("rev-parse", "HEAD");
    // merge_group.base_sha is the preceding candidate's head, not the develop tip.
    assert.deepEqual(changedFiles(preceding, head, cwd), [appFile]);
    let run = scope(preceding, head);
    assert.equal(run.status, 0, run.stderr);
    assert.match(run.stdout, /^full=false$/m);
    assert.match(run.stdout, /^frontend=true$/m);
    assert.match(run.stdout, /^backend=false$/m);
    fs.mkdirSync(path.join(cwd, "docs"));
    git("mv", backendFile, "docs/moved.md");
    git("commit", "--quiet", "-m", "move out of backend");
    const moved = git("rev-parse", "HEAD");
    assert.deepEqual(changedFiles(head, moved, cwd).sort(), [backendFile, "docs/moved.md"].sort());
    assert.throws(() => changedFiles("", moved, cwd));
    // Missing history is a full-run fallback at the CLI boundary.
    run = scope("f".repeat(40), moved);
    assert.equal(run.status, 0, run.stderr);
    assert.match(run.stdout, /^full=true$/m);
    assert.match(run.stdout, /^docker=true$/m);
  } finally {
    fs.rmSync(cwd, { recursive: true, force: true });
  }
});
