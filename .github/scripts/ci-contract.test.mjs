import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { checkBuildMemory, readPeakRssMb } from "./ci-build-memory.mjs";
import { changedFiles, planCi } from "./ci-change-scope.mjs";
import { evaluateCi } from "./ci-gate.mjs";
import { CI_WORKFLOW, proves } from "./ci-publication-acceptance.mjs";

const root = fileURLToPath(new URL("../../", import.meta.url));
const appFile = "frontend/apps/web/src/routes/+page.svelte";
const backendFile = "backend/src/eneo/server/main.py";
const docsFile = "frontend/apps/docs-site/src/content/contributing/index.mdx";
const resultsFor = (plan) => Object.fromEntries(Object.entries(plan.expected_jobs)
  .map(([job, required]) => [job, { result: required ? "success" : "skipped" }]));

for (const event of ["pull_request"]) {
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
    const plan = planCi([file], "pull_request");
    for (const name of ["frontend", "frontend_e2e", "web_next", "web_next_e2e"]) assert.equal(plan[name], true, `${file}: ${name}`);
    assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["backend", "frontend"]);
  }
});

test("workflow, local action, scope and gate changes force full validation", () => {
  for (const file of [".github/workflows/ci.yml", ".github/actions/setup-playwright/action.yml", ".github/scripts/ci-gate.mjs", ".github/scripts/ci-web-next-e2e-legs.mjs"]) {
    const plan = planCi([file], "pull_request");
    assert.equal(plan.full, true);
    assert.equal(plan.docker_matrix.include.length, 3);
  }
});

test("apt has deadlines only on its network phase and installs nothing it did not download", () => {
  const action = fs.readFileSync(path.join(root, ".github/actions/setup-playwright/action.yml"), "utf8");
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  assert.match(action, /playwright install-deps --dry-run chromium/);
  assert.match(action, /"\$GITHUB_WORKSPACE\/\.github\/scripts\/ci-apt-install\.sh" "\$\{missing\[@\]\}"/);
  assert.doesNotMatch(action, /^        bun run --bun playwright install-deps chromium$/m);

  // Stubs record every apt-get call and whether it ran under `timeout`; FAIL_DOWNLOADS
  // download attempts fail before one succeeds.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "eneo-ci-apt-"));
  try {
    const log = path.join(dir, "apt.log");
    const stub = (name, body) => fs.writeFileSync(path.join(dir, name), `#!/usr/bin/env bash\n${body}\n`, { mode: 0o755 });
    // `sed -i` without a suffix is GNU syntax; on macOS the stub supplies BSD's empty one.
    stub("sudo", [
      '[ "$1" = tee ] && { cat >/dev/null; exit 0; }',
      'if [ "$1" = sed ] && ! sed --version >/dev/null 2>&1; then shift 2; exec sed -i "" "$@"; fi',
      'exec "$@"',
    ].join("\n"));
    stub("timeout", 'shift 2\nDEADLINE=1 exec "$@"');
    stub("apt-get", [
      'echo "${DEADLINE:+deadline }$*" >> "$APT_LOG"',
      'if [[ "$*" == *--download-only* ]]; then',
      '  n=$(grep -c -- --download-only "$APT_LOG")',
      '  [ "$n" -gt "${FAIL_DOWNLOADS:-0}" ]',
      "fi",
    ].join("\n"));
    const mirrors = path.join(dir, "apt-mirrors.txt");
    const hosted = "http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\nhttps://archive.ubuntu.com/ubuntu/\tpriority:2\n"
      + "https://security.ubuntu.com/ubuntu/\tpriority:3\n";
    const run = (args, failDownloads, mirrorList = hosted) => {
      fs.rmSync(log, { force: true });
      fs.writeFileSync(mirrors, mirrorList);
      const result = spawnSync("bash", [path.join(root, ".github/scripts/ci-apt-install.sh"), ...args], {
        encoding: "utf8", timeout: 10_000,
        env: {
          ...process.env, PATH: `${dir}:${process.env.PATH}`, APT_LOG: log, APT_MIRRORS: mirrors,
          FAIL_DOWNLOADS: String(failDownloads),
        },
      });
      const calls = fs.existsSync(log) ? fs.readFileSync(log, "utf8").trim().split("\n") : [];
      return { status: result.status, calls, mirrors: fs.readFileSync(mirrors, "utf8") };
    };
    const update = "deadline -q update";
    const download = "deadline -q install -y --no-install-recommends --download-only fonts-a fonts-b";
    const install = "install -y -q --no-install-recommends --no-download fonts-a fonts-b";

    const fallback = hosted.split("\n").slice(1).join("\n");
    assert.deepEqual(run(["fonts-a", "fonts-b"], 0), { status: 0, calls: [update, download, install], mirrors: hosted });
    // A failed download leaves the Azure mirror and resumes; dpkg still runs only after it.
    assert.deepEqual(run(["fonts-a", "fonts-b"], 1),
      { status: 0, calls: [update, download, download, install], mirrors: fallback });
    // Three failed downloads stop the job without starting dpkg, and keep the other mirrors.
    assert.deepEqual(run(["fonts-a", "fonts-b"], 3),
      { status: 1, calls: [update, download, download, download], mirrors: fallback });
    // A runner without the Azure mirror (an AWS-hosted one) retries on its own list.
    assert.deepEqual(run(["fonts-a", "fonts-b"], 1, fallback),
      { status: 0, calls: [update, download, download, install], mirrors: fallback });
    assert.deepEqual(run([], 0), { status: 0, calls: [], mirrors: hosted });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }

  // Three bounded attempts per phase still leave the rest of each Playwright job its time.
  const jobs = workflow.split("\njobs:\n")[1].split(/\n(?=  [a-z][a-z0-9-]*:\n)/)
    .filter((block) => block.includes("uses: ./.github/actions/setup-playwright"));
  assert.ok(jobs.length > 0);
  for (const block of jobs) {
    const limit = Number(block.match(/^    timeout-minutes: (\d+)$/m)?.[1]);
    assert.ok(limit >= 30, `${block.match(/^  ([a-z0-9-]+):/)[1]}: ${limit} min`);
  }
});

test("both E2E jobs free disk before building their stack", () => {
  // AWS-hosted runners ran out of space during the stack build (jobs 125460893789, 125544852231).
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  for (const [name, next] of [["frontend-e2e", "frontend-web-next-e2e"], ["frontend-web-next-e2e", "schema-drift"]]) {
    const job = workflow.split(`\n  ${name}:\n`)[1].split(`\n  ${next}:\n`)[0];
    const guard = job.indexOf("uses: ./.github/actions/free-disk");
    assert.ok(guard > job.indexOf("- name: Checkout"), name);
    assert.ok(guard < job.indexOf("- name: Start isolated E2E stack in the background"), name);
  }
});

test("E2E stacks keep their network inside their compose project", () => {
  // A fixed network name let stacks started side by side with their own -p resolve each other's e2e-db and e2e-redis.
  for (const file of ["docker-compose.e2e.yml", "docker-compose.e2e.ci.yml"]) {
    const networks = fs.readFileSync(path.join(root, file), "utf8").split("\nnetworks:\n")[1].split(/\n(?=\S)/)[0];
    assert.match(networks, /^ {2}e2e: \{\}$/m, file);
    assert.doesNotMatch(networks, /^ +name:/m, file);
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
  const step = (name) => job.split(`- name: ${name}\n`)[1]?.split(/\n      - name: /)[0];
  assert.doesNotMatch(job, /next start|next-web-next|SESSION_SECRET|\.next\/cache/);
  const native = step("Run E2E and accessibility tests");
  const upload = step("Run the native knowledge upload test");
  const worker = step("Start and check the knowledge upload worker");
  // Complementary selections cover every case without starting the worker before queued-result tests.
  assert.deepEqual([...job.matchAll(/^        run: (bun run test:e2e.*)$/gm)].map((match) => match[1]), [
    'bun run test:e2e --grep "$E2E_GREP" --grep-invert "$E2E_GREP_INVERT"',
    "bun run test:e2e --grep '@upload-worker' --output test-results/upload-worker",
  ]);
  assert.ok(native?.includes("E2E_GREP: ${{ matrix.grep }}\n"));
  assert.ok(native.includes("E2E_GREP_INVERT: ${{ matrix.grep_invert }}\n"));
  for (const body of [native, upload]) {
    assert.match(body ?? "", /E2E_BASE_URL: http:\/\/localhost:8124/);
    assert.match(body, /working-directory: frontend\/apps\/web-next/);
  }
  for (const body of [native, worker, upload]) {
    assert.equal(typeof body, "string");
    assert.doesNotMatch(body, /^        continue-on-error:/m, "test phases require preceding success");
  }
  assert.doesNotMatch(native, /^        if:/m, "test phases require preceding success");
  // A condition without a status function implies success(), so the worker phases still require it.
  for (const body of [worker, upload]) {
    assert.deepEqual(body.match(/^        if: .*$/gm), ["        if: matrix.upload_worker"]);
  }
  // Each leg has its own stack and report. The walk legs exclude the upload case; the rest
  // leg excludes it and both walk selections, so the legs run every other case exactly once.
  assert.match(job, /^    strategy:\n      fail-fast: false\n      matrix:\n        include:\n/m);
  const include = job.split("        include:\n")[1].split("\n    steps:")[0].split("\n");
  const legs = include.map((line) => line.match(
    /^          - \{ leg: ([a-z0-9-]+), grep: "([^"]+)", grep_invert: "([^"]+)"(, upload_worker: true)? \}$/,
  )).map((match) => match && { leg: match[1], grep: match[2], invert: match[3], worker: Boolean(match[4]) });
  assert.ok(legs.length >= 2 && legs.every(Boolean), include.join("\n"));
  assert.equal(new Set(legs.map(({ leg }) => leg)).size, legs.length, "artifact names are unique");
  assert.equal(legs.filter(({ worker }) => worker).length, 1, "the upload case runs once");
  // Walk legs select by tag; file legs select specs by name and exclude the walks; the rest
  // leg excludes both.
  const walks = legs.filter(({ grep }) => grep.startsWith("@"));
  const files = legs.filter(({ grep }) => grep !== "." && !grep.startsWith("@"));
  const rest = legs.filter(({ grep }) => grep === ".");
  assert.equal(rest.length, 1);
  for (const { invert } of walks) assert.equal(invert, "@upload-worker");
  const notWalks = ["@upload-worker", ...walks.map(({ grep }) => grep)].join("|");
  for (const { invert } of files) assert.equal(invert, notWalks);
  assert.equal(rest[0].invert, [notWalks, ...files.map(({ grep }) => grep)].join("|"));
  // A walk leg selects cells: a walk's tag, or its tag and a viewport's device, which
  // walkTags (tests/responsive-fixtures.ts) puts right after it. Which cases each leg
  // then holds is checked against Playwright's own listing by ci-web-next-e2e-legs.mjs.
  const cells = walks.flatMap(({ grep }) => grep.split("|"));
  assert.equal(new Set(cells).size, cells.length, "each cell runs in one leg");
  const parsed = cells.map((cell) => cell.match(/^(@[a-z0-9-]+)(?: @([a-z]+))?$/));
  assert.ok(parsed.every(Boolean), cells.join("|"));
  const tags = [...new Set(parsed.map(([, tag]) => tag))];
  const unit = workflow.split("\n  frontend-web-next:\n")[1].split("\n  frontend-e2e:\n")[0];
  assert.match(unit, /^        run: node \.\.\/\.github\/scripts\/ci-web-next-e2e-legs\.mjs$/m);
  const testsDir = path.join(root, "frontend/apps/web-next/tests");
  const specs = fs.readdirSync(testsDir).filter((file) => file.endsWith(".spec.ts"))
    .map((file) => [file, fs.readFileSync(path.join(testsDir, file), "utf8")]);
  // Playwright matches --grep, case-insensitively, against the title path, which holds the
  // spec's file name between spaces.
  const selects = (grep, file) => new RegExp(grep, "i").test(` smoke ${file} `);
  // A tag or file pattern that selects nothing would quietly move its walk into the rest leg.
  for (const tag of tags) assert.ok(specs.some(([, source]) => source.includes(`"${tag}"`)), tag);
  for (const { leg, grep } of files) assert.ok(specs.some(([file]) => selects(grep, file)), leg);
  // A whole-route walk (a test limit of ten minutes or more) must not land in the rest leg.
  for (const [file, source] of specs) {
    const limits = [...source.matchAll(/test\.setTimeout\(([\d_]+)( \* 60_000)?\)/g)]
      .map(([, value, minutes]) => Number(value.replaceAll("_", "")) * (minutes ? 60_000 : 1));
    if (limits.some((ms) => ms >= 10 * 60_000)) {
      const led = tags.some((tag) => source.includes(`"${tag}"`)) || files.some(({ grep }) => selects(grep, file));
      assert.ok(led, `${file}: a route walk outside the walk and file legs`);
    }
  }
  const workerIndex = job.indexOf("- name: Start and check the knowledge upload worker");
  assert.ok(workerIndex > job.indexOf("- name: Run E2E and accessibility tests"));
  assert.ok(workerIndex < job.indexOf("- name: Run the native knowledge upload test"));
  assert.match(worker, /e2e-backend sh -c 'exec \/app\/\.venv\/bin\/worker/);
  assert.match(worker, /e2e-backend \/app\/\.venv\/bin\/worker --check; then\n\s+exit 0/);
  assert.match(worker, /done\n\s+exit 1/);
  assert.match(upload, /PLAYWRIGHT_HTML_OUTPUT_DIR: playwright-report\/upload-worker/);
  const report = step("Upload Playwright report") ?? "";
  assert.ok(report.includes("name: playwright-report-web-next-${{ matrix.leg }}\n"));
  for (const directory of ["playwright-report", "test-results", "playwright-report-fastapi", "test-results-fastapi"]) {
    assert.ok(report.includes(`frontend/apps/web-next/${directory}\n`), directory);
  }
  assert.ok(report.includes("if: ${{ !cancelled() }}"));
  const stop = step("Stop E2E stack") ?? "";
  assert.ok(stop.includes("if: ${{ always() }}"));
  assert.match(stop, /docker compose .* down -v/);
  const assets = job.indexOf("- name: Copy browser asset map from the running backend");
  assert.ok(assets > job.indexOf("- name: Wait for the E2E stack"));
  assert.ok(assets < job.indexOf("- name: Run E2E and accessibility tests"));
  assert.match(job.slice(assets), /e2e-backend:\/app\/web-bundle-report.json frontend\/apps\/web-next\/node_modules\/\.cache\/vite-bundle-report.json/);
  // Production images and the web-next stack build the Vite app; the Svelte stack, which never serves it, does not.
  const dockerfile = fs.readFileSync(path.join(root, "backend/Dockerfile"), "utf8");
  assert.match(dockerfile, /^ARG WEB_APP_STAGE=web-build$/m);
  assert.match(dockerfile, /^FROM \$\{WEB_APP_STAGE\} AS web-app$/m);
  assert.match(dockerfile, /COPY --from=web-app .*\/vite-bundle-report.json \/app\/web-bundle-report.json/);
  const compose = (file) => fs.readFileSync(path.join(root, file), "utf8");
  assert.match(compose("docker-compose.e2e.ci.yml"), /^ {8}WEB_APP_STAGE: no-web-app$/m);
  assert.match(compose("docker-compose.e2e.web-app.yml"), /^ {8}WEB_APP_STAGE: web-build$/m);
});

test("web-next rejects route drift before type checking", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const job = workflow.split("\n  frontend-web-next:\n")[1].split("\n  frontend-e2e:\n")[0];
  const step = (name) => job.split(`- name: ${name}\n`)[1]?.split(/\n      - name: /)[0];
  assert.match(job, /working-directory: frontend\n/);
  assert.match(step("Check route tree drift") ?? "", /routes:generate && git diff --exit-code -- apps\/web-next\/src\/routeTree\.gen\.ts/);
  assert.ok(job.indexOf("- name: Check route tree drift") < job.indexOf("- name: Type check"));
});

test("publications running side by side never cancel or replace each other's work", () => {
  const read = (file) => fs.readFileSync(path.join(root, ".github/workflows", file), "utf8");
  // Called by image publication, CI carries the caller's workflow name and belongs to that run.
  const ci = read("ci.yml").split("\nconcurrency:\n")[1].split("\n\n")[0];
  assert.equal(ci, [
    "  group: ${{ github.workflow == 'CI' && format('CI-{0}', github.event.pull_request.number || github.ref) || format('{0}-checks-{1}', github.workflow, github.run_id) }}",
    "  cancel-in-progress: ${{ github.workflow == 'CI' }}",
  ].join("\n"));
  // The user-facing check ci.yml calls cancels only an older run of the same pull request.
  const userFacing = read("user-facing.yml").split("\nconcurrency:\n")[1].split("\n\n")[0];
  assert.equal(userFacing, [
    "  group: ${{ github.event_name == 'pull_request' && format('user-facing-{0}-{1}', github.workflow, github.event.pull_request.number) || format('user-facing-{0}-{1}', github.workflow, github.run_id) }}",
    "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
  ].join("\n"));
  // One tool-runtime publisher per version, and a waiting one is never replaced.
  const runtime = read("tool_runtime_image.yml").split("\n  image:\n")[1].split("\n    permissions:")[0];
  assert.match(runtime, /^      group: eneo-image-tool-runtime-\$\{\{ needs\.test\.outputs\.publish == 'true' && needs\.test\.outputs\.version \|\| github\.run_id \}\}\n      queue: max\n      cancel-in-progress: false$/m);
});

test("publication reuses CI only through a full-suite receipt from the merge queue on that commit", () => {
  const repository = "eneo-ai/eneo";
  const sha = "a".repeat(40);
  const run = {
    id: 7, run_attempt: 2, event: "merge_group", path: CI_WORKFLOW, head_sha: sha,
    repository: { full_name: repository }, head_repository: { full_name: repository },
    status: "completed", conclusion: "success",
  };
  const receipt = {
    schema: 1, sha, repository, workflow: `${repository}/${CI_WORKFLOW}@refs/heads/gh-readonly-queue/develop/pr-1-x`,
    event: "merge_group", run_id: 7, run_attempt: 2, scope: "full",
  };
  assert.equal(proves(run, receipt, { sha, repository }), true);
  for (const [field, value] of [
    ["event", "pull_request"], ["path", ".github/workflows/other.yml"], ["head_sha", "b".repeat(40)],
    ["repository", { full_name: "fork/eneo" }], ["head_repository", { full_name: "fork/eneo" }],
    ["status", "in_progress"], ["conclusion", "failure"],
  ]) assert.equal(proves({ ...run, [field]: value }, receipt, { sha, repository }), false, `run ${field}`);
  for (const [field, value] of [
    ["schema", 2], ["sha", "b".repeat(40)], ["repository", "fork/eneo"], ["event", "push"],
    ["workflow", `${repository}/.github/workflows/build_and_push_images.yml@refs/heads/develop`],
    ["run_id", 8], ["run_attempt", 1], ["scope", "scoped"],
  ]) assert.equal(proves(run, { ...receipt, [field]: value }, { sha, repository }), false, `receipt ${field}`);
  assert.equal(proves(run, undefined, { sha, repository }), false);

  // CI writes the receipt only after its gate passed, from the scope the run planned.
  const ci = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const gate = ci.slice(ci.indexOf("\n  ci:\n"));
  assert.ok(gate.indexOf("run: node .github/scripts/ci-gate.mjs") < gate.indexOf("- name: Write the validation receipt"));
  assert.match(gate, /FULL: \$\{\{ needs\.changes\.outputs\.full \}\}/);
  // Only merge-queue runs write one: elsewhere an artifact-service failure must not fail CI.
  for (const name of ["Write the validation receipt", "Keep the validation receipt"]) {
    assert.match(gate.split(`- name: ${name}\n`)[1], /^        if: github\.event_name == 'merge_group'\n/, name);
  }
  assert.match(gate, /name: ci-receipt\n {10}path: ci-receipt\.json\n {10}retention-days: 14\n {10}overwrite: true/);

  const workflow = fs.readFileSync(path.join(root, ".github/workflows/build_and_push_images.yml"), "utf8");
  const job = (name) => workflow.split(`\n  ${name}:\n`)[1].split(/\n  [a-z-]+:\n/)[0];
  assert.match(job("acceptance"), /^    permissions:\n      actions: read\n      contents: read\n/m);
  assert.match(job("checks"), /^    needs: \[release, acceptance\]\n    if: needs\.acceptance\.outputs\.reuse != 'true'\n    uses: \.\/\.github\/workflows\/ci\.yml$/m);
  assert.match(job("security"), /^    if: needs\.acceptance\.outputs\.reuse == 'true'\n    uses: \.\/\.github\/workflows\/security\.yml$/m);
  assert.ok(job("accepted").includes(`[[ "$CHECKS" == success || ( "$REUSE" == true && "$CHECKS" == skipped && "$SECURITY" == success ) ]]`));
  assert.match(job("bundle"), /^    needs: \[release, accepted, /m);
  // One of checks and security is always skipped: without their own status checks the
  // jobs after accepted would be skipped with it.
  assert.ok(job("bundle").includes("&& needs.accepted.result == 'success'"));
  assert.match(job("bundle"), /\$\{\{ !cancelled\(\)/);
  assert.match(job("release-sbom"), /^    if: \$\{\{ !cancelled\(\) && needs\.bundle\.result == 'success' && startsWith\(github\.ref, 'refs\/tags\/v'\) \}\}$/m);
});

test("publication moves aliases only from its bundle, under the release controller's lock", () => {
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/build_and_push_images.yml"), "utf8");
  const job = (name) => workflow.split(`\n  ${name}:\n`)[1].split(/\n  [a-z-]+:\n/)[0];
  assert.doesNotMatch(job("bundle"), /release_bundle\.py promote|packages: write/);
  const promote = job("promote");
  assert.match(promote, /^    needs: \[release, verify, bundle, release-sbom\]$/m);
  const lock = "    concurrency:\n      group: eneo-release-lifecycle\n      queue: max\n      cancel-in-progress: false\n";
  assert.ok(promote.includes(lock));
  // The controller takes the same lock on its job, so skipped completions never queue in it.
  const release = fs.readFileSync(path.join(root, ".github/workflows/release.yml"), "utf8");
  assert.doesNotMatch(release, /^concurrency:/m);
  assert.ok(release.split("\n  reconcile:\n")[1].includes(lock));
  assert.match(promote, /^    permissions:\n      contents: read\n      packages: write\n    steps:$/m);
  // A final release moves latest after its SBOM; develop and branches, whose SBOM job is skipped, still move.
  assert.ok(promote.includes("needs.release-sbom.result == 'success'"));
  assert.ok(promote.includes("(needs.release-sbom.result == 'skipped' && !startsWith(github.ref, 'refs/tags/'))"));
  assert.match(promote, /^        if: needs\.release\.outputs\.managed != 'true'\n        run: python3 scripts\/release_bundle\.py promote --bundle release-bundle\/release\.json$/m);
  assert.equal(workflow.match(/release_bundle\.py promote/g).length, 1);
});

test("publication serializes a version's writes by that version, and nothing else", () => {
  const read = (file) => fs.readFileSync(path.join(root, ".github/workflows", file), "utf8");
  const workflow = read("build_and_push_images.yml");
  assert.doesNotMatch(workflow, /^concurrency:/m);
  const lock = (group) => `    concurrency:\n      group: ${group}\n      queue: max\n      cancel-in-progress: false\n`;
  assert.ok(read("application_image.yml").includes(lock("eneo-image-${{ inputs.component }}-${{ inputs.version }}")));
  assert.ok(workflow.split("\n  bundle:\n")[1].includes(lock("eneo-bundle-${{ needs.release.outputs.version }}")));
  // The tag's SBOM publisher queues too: a waiting retry is never replaced.
  assert.match(read("release_sbom.yml"), /^concurrency:\n  group: eneo-release-sbom-\$\{\{ inputs\.tag \}\}\n  queue: max\n  cancel-in-progress: false$/m);
});

test("publication's CI skips only the backend and frontend dry-run builds it publishes itself", () => {
  const plan = planCi([], "push", { publication: true });
  assert.equal(plan.full, true);
  assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["devcontainer"]);
  assert.equal(plan.expected_jobs["docker-builds"], true);
  assert.equal(planCi([], "push").docker_matrix.include.length, 3);
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/build_and_push_images.yml"), "utf8");
  assert.match(workflow.split("\n  checks:\n")[1].split(/\n  [a-z-]+:\n/)[0], /^    with:\n(?:      #.*\n)*      publication: true$/m);
  assert.match(fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8"), /CI_PUBLICATION: \$\{\{ inputs\.publication \}\}/);
});

test("the frontend image builds beside the backend, with its release version and no cache export", () => {
  const publication = fs.readFileSync(path.join(root, ".github/workflows/build_and_push_images.yml"), "utf8");
  assert.match(publication.split("\n  frontend:\n")[1], /^    needs: release\n/);
  const image = fs.readFileSync(path.join(root, ".github/workflows/application_image.yml"), "utf8");
  assert.doesNotMatch(image, /backend_digest|sync-frontend-with-backend/);
  assert.match(image, /sudo fallocate -l 6G \/mnt\/eneo-frontend\.swap/);
  assert.match(image, /test "\$\(jq -r \.version frontend\/apps\/web\/package\.json\)" = "\$VERSION"/);
  assert.match(image, /cache-to: \$\{\{ inputs\.component != 'frontend' && /);
  // The bundle is published only after acceptance; verifying it does not wait for that.
  assert.match(publication.split("\n  verify:\n")[1], /^    needs: \[release, backend, frontend, tool-runtime\]\n/);
  assert.match(publication.split("\n  bundle:\n")[1], /^    needs: \[release, accepted, verify\]\n/);
  // The bundle files cross jobs as an artifact: bundle and promote use them only if they
  // are the files verify checked.
  assert.match(publication.split("\n  verify:\n")[1], /^    outputs:\n      sums: \$\{\{ steps\.bundle\.outputs\.sums \}\}$/m);
  const check = "          test \"$(ls -A | sort | tr '\\n' ' ')\" = \"release.env release.json \"\n          base64 -d <<<\"$SUMS\" | sha256sum -c -\n";
  // Only those two files are uploaded, attested and published.
  assert.doesNotMatch(publication, /release-bundle\/\*|path: release-bundle\/\n/);
  assert.match(publication, /subject-path: release-bundle\/release\.json,release-bundle\/release\.env$/m);
  for (const name of ["bundle", "promote"]) {
    const block = publication.split(`\n  ${name}:\n`)[1].split(/\n  [a-z-]+:\n/)[0];
    assert.ok(block.indexOf(check) > 0, name);
    assert.ok(block.indexOf(check) < block.indexOf(name === "bundle" ? "Attest the complete bundle" : "release_bundle.py promote"), name);
  }
  assert.ok(publication.split("\n  bundle:\n")[1].includes("&& needs.verify.result == 'success'"));
});

test("the bundle check passes only the two files verify checked, unchanged", () => {
  const publication = fs.readFileSync(path.join(root, ".github/workflows/build_and_push_images.yml"), "utf8");
  const script = publication.split("\n  bundle:\n")[1].split("- name: Check the bundle is the one verify checked\n")[1]
    .split("\n        run: |\n")[1].split(/\n      - /)[0].replace(/^ {10}/gm, "");
  const files = { "release.json": "{\"version\": \"1\"}\n", "release.env": "ENEO_VERSION=1\n" };
  const sums = Buffer.from(Object.entries(files)
    .map(([name, content]) => `${crypto.createHash("sha256").update(content).digest("hex")}  ${name}\n`).join("")).toString("base64");
  const check = (change) => {
    const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "eneo-bundle-check-"));
    try {
      fs.mkdirSync(path.join(cwd, "release-bundle"));
      for (const [name, content] of Object.entries(files)) fs.writeFileSync(path.join(cwd, "release-bundle", name), content);
      change(path.join(cwd, "release-bundle"));
      return spawnSync("bash", ["-e", "-c", script], { cwd, env: { ...process.env, SUMS: sums }, encoding: "utf8" }).status;
    } finally {
      fs.rmSync(cwd, { recursive: true, force: true });
    }
  };
  assert.equal(check(() => {}), 0);
  assert.notEqual(check((dir) => fs.appendFileSync(path.join(dir, "release.json"), " ")), 0);
  assert.notEqual(check((dir) => fs.writeFileSync(path.join(dir, "payload.sh"), "exit 0\n")), 0);
  assert.notEqual(check((dir) => fs.rmSync(path.join(dir, "release.env"))), 0);
});

test("only develop pushes save the package download cache", () => {
  // Pull request and merge-queue refs saved their own ~610 MB copy that no other ref could restore.
  const action = fs.readFileSync(path.join(root, ".github/actions/setup-frontend/action.yml"), "utf8");
  const step = (name) => action.split(`- name: ${name}\n`)[1]?.split(/\n    - /)[0] ?? "";
  const restore = step("Restore the package download cache");
  const save = step("Save the package download cache");
  assert.doesNotMatch(action, /uses: actions\/cache@/);
  assert.match(restore, /^      id: bun-cache$/m);
  assert.match(restore, /^      uses: actions\/cache\/restore@[0-9a-f]{40} # v4$/m);
  assert.match(restore, /^        restore-keys: bun-/m);
  assert.equal(save.match(/^      if: (.*)$/m)?.[1],
    "github.event_name == 'push' && github.ref == 'refs/heads/develop' && steps.bun-cache.outputs.cache-hit != 'true'");
  assert.match(save, /^      uses: actions\/cache\/save@[0-9a-f]{40} # v4$/m);
  assert.match(save, /^        key: \$\{\{ steps\.bun-cache\.outputs\.cache-primary-key \}\}$/m);
  const cachePath = (body) => body.match(/^        path: (.*)$/m)?.[1];
  assert.equal(cachePath(save), cachePath(restore));
  const order = ["Restore the package download cache", "Install locked workspace dependencies", "Save the package download cache"]
    .map((name) => action.indexOf(`- name: ${name}\n`));
  assert.ok(order.every((index, i) => index > (order[i - 1] ?? -1)), String(order));
});

test("the migrations leg runs every migration_isolation test file exactly once", () => {
  // A round trip that only a hand-written list ran never ran once nobody added it to the list.
  // Discovery over all of tests/ finds a marked file in any directory and under either name pattern.
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const step = (name) => workflow.split(`- name: ${name}\n`)[1]?.split(/\n      - name: /)[0] ?? "";
  const roundTrips = step("Verify migration round trips");
  const fileIcon = step("Verify File/Icon upgrade and optional cleanup on PostgreSQL 13");
  assert.match(roundTrips, /^        if: matrix\.suite == 'migrations'$/m);
  assert.match(roundTrips, /--collect-only -m migration_isolation tests \\$/m);
  // One process per module: modules that share the session database start from a fresh schema.
  assert.match(roundTrips, /for module in "\$\{modules\[@\]\}"; do\n\s+uv run pytest -q -m migration_isolation "\$module" \|\| status=1/);
  const ignored = [...roundTrips.matchAll(/--ignore=(\S+)/g)].map(([, file]) => file);
  const dedicated = [...fileIcon.matchAll(/(tests\/integration\/\S+\.py)/g)].map(([, file]) => file);
  assert.ok(ignored.length > 0);
  assert.deepEqual([...ignored].sort(), [...new Set(dedicated)].sort(), "ignored files run in the File/Icon step");
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
  const plan = planCi([backendFile, appFile], "pull_request");
  assert.equal(plan.backend, true);
  assert.equal(plan.frontend, true);
  assert.equal(plan.web_next_e2e, true);
  assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["backend", "frontend"]);
});

test("empty diffs run the full suite", () => {
  assert.equal(planCi([], "pull_request").full, true);
});

test("unmapped runtime and root configuration paths run the full suite", () => {
  for (const file of ["new-service/main.py", ".env.example", "docker-compose.yml"]) {
    assert.equal(planCi([file], "pull_request").full, true, file);
  }
});

test("the release-notes check runs on every change, in the scope job", () => {
  // It reads the Svelte app, web-next and the backend's legacy-page map: a job
  // scoped to one app would let a change in another break the next release.
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  const jobs = workflow.split("\njobs:\n")[1].split(/\n(?=  [a-z][a-z0-9-]*:\n)/);
  const owners = jobs.filter((job) => job.includes("scripts/check_whats_new.py"));
  assert.equal(owners.length, 1);
  assert.match(owners[0], /^  changes:\n/);
  const step = owners[0].split("- name: Check What's new release notes\n")[1].split(/\n      - name: /)[0];
  assert.doesNotMatch(step, /\n        if:/);
});

test("contract inputs select their consumers and developer tooling", () => {
  const cases = [
    ["backend/src/eneo/roles/permissions.py", ["backend", "scripts", "route_metadata"]],
    ["scripts/backend_test_shard.py", ["backend", "scripts"]],
    ["scripts/check_whats_new.py", ["scripts"]],
    ["frontend/packages/whats-new/version-order.cases.json", ["backend", "frontend", "scripts"]],
    ["frontend/apps/web-next/src/lib/auth/safe-next.cases.json", ["backend", "web_next", "web_next_e2e"]],
    ["frontend/packages/whats-new/releases.schema.json", ["backend", "frontend", "scripts"]],
    ["frontend/packages/eneo-js/src/types/schema.d.ts", ["schema", "frontend", "web_next"]],
    [".github/scripts/project-intake.mjs", ["scripts"]],
    ["e2e/mock_model_server.py", ["frontend_e2e", "web_next_e2e"]],
    [".devcontainer/Dockerfile", ["docker_devcontainer"]],
  ];
  for (const [file, required] of cases) {
    const plan = planCi([file], "pull_request");
    for (const name of required) assert.equal(plan[name], true, `${file}: ${name}`);
  }
  assert.equal(planCi([backendFile], "pull_request").scripts, false);
});

test("web-next-only changes do not build the Svelte app", () => {
  const plan = planCi(["frontend/apps/web-next/src/routes/index.tsx"], "pull_request");
  assert.equal(plan.web_next, true);
  assert.equal(plan.web_next_e2e, true);
  assert.equal(plan.frontend, false);
  assert.equal(plan.frontend_e2e, false);
  assert.deepEqual(plan.docker_matrix.include.map(({ image }) => image), ["backend"]);
});

test("web-next inputs rebuild the backend image that bundles the web app", () => {
  for (const file of ["frontend/bunfig.toml", "frontend/apps/web-next/src/main.tsx"]) {
    const plan = planCi([file], "pull_request");
    const backend = plan.docker_matrix.include.find(({ image }) => image === "backend");
    assert.equal(backend?.build_contexts, "web=./frontend", file);
  }
  const workflow = fs.readFileSync(path.join(root, ".github/workflows/ci.yml"), "utf8");
  assert.match(workflow, /build-contexts: \$\{\{ matrix\.build_contexts \}\}/);
});

test("missing, failed, cancelled and unexpectedly skipped required jobs fail the gate", () => {
  const plan = planCi([appFile], "pull_request");
  for (const job of Object.keys(plan.expected_jobs).filter((job) => plan.expected_jobs[job])) {
    for (const result of ["failure", "cancelled", "skipped", "timed_out", undefined]) {
      const needs = resultsFor(plan);
      needs[job] = result ? { result } : undefined;
      assert.ok(evaluateCi(plan.expected_jobs, needs).some((error) => error.startsWith(`${job}:`)), `${job}: ${result}`);
    }
  }
});

test("optional jobs cannot hide a failure and unknown jobs cannot bypass the gate", () => {
  const plan = planCi([docsFile], "pull_request");
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
  const plan = planCi([docsFile], "pull_request");
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

test("a pull request is classified by its own diff, the merge queue runs everything, and a bad base runs everything", () => {
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
    const scope = (baseSha, head, event = "pull_request") => {
      const eventPath = path.join(cwd, "event.json");
      fs.writeFileSync(eventPath, JSON.stringify(event === "pull_request"
        ? { pull_request: { base: { sha: baseSha } } } : { merge_group: { base_sha: baseSha } }));
      return spawnSync(process.execPath, [path.join(root, ".github/scripts/ci-change-scope.mjs"), "--github-event"], {
        cwd, encoding: "utf8", timeout: 5_000,
        env: { ...process.env, GITHUB_EVENT_NAME: event, GITHUB_EVENT_PATH: eventPath, GITHUB_SHA: head, GITHUB_STEP_SUMMARY: "" },
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
    assert.deepEqual(changedFiles(preceding, head, cwd), [appFile]);
    let run = scope(preceding, head);
    assert.equal(run.status, 0, run.stderr);
    assert.match(run.stdout, /^full=false$/m);
    assert.match(run.stdout, /^frontend=true$/m);
    assert.match(run.stdout, /^backend=false$/m);
    // A queue entry's diff leaves out the entries ahead of it, and publication reuses
    // the queue's result for the commit that lands: the queue validates everything.
    run = scope(preceding, head, "merge_group");
    assert.equal(run.status, 0, run.stderr);
    assert.match(run.stdout, /^full=true$/m);
    assert.match(run.stdout, /^backend=true$/m);
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

test("tool-runtime document engine files run the backend suite", () => {
  // Flow document tests render through the tool runtime's document engine.
  const plan = planCi(["tool-runtime/src/tools/documents/control.ts"], "merge_group");
  assert.equal(plan.backend, true);
});
