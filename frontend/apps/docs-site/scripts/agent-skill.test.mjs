import { expect, test } from "bun:test";
import { access, readFile, readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const appDir = dirname(dirname(fileURLToPath(import.meta.url)));
const skillDir = join(appDir, "skills", "eneo-flows-api");
const skillFile = join(skillDir, "SKILL.md");
const evaluationFile = join(skillDir, "evals", "evals.json");
const triggerQueriesFile = join(skillDir, "evals", "eval_queries.json");
const packageFile = join(appDir, "public", "skills", "eneo-flows-api.skill");
const packageScript = join(appDir, "scripts", "package-agent-skill.py");
const docsPage = join(
  appDir,
  "src",
  "content",
  "guides",
  "flows",
  "agent-skill.mdx",
);

const expectedReferences = [
  "endpoints-and-errors.md",
  "inputs-and-results.md",
  "integration-workflow.md",
  "review-evidence-and-retention.md",
  "typescript-patterns.md",
];

test("the Eneo Flows API skill has valid discovery metadata", async () => {
  const source = await readFile(skillFile, "utf8");
  const frontmatter = source.match(/^---\n([\s\S]*?)\n---/)?.[1];

  expect(frontmatter).toBeDefined();
  expect(frontmatter).toContain("name: eneo-flows-api");
  expect(frontmatter).toContain("description: Use this skill when");
  expect(frontmatter).toContain("Do not use for Flow AI Builder");
  const description = frontmatter?.match(/^description: (.+)$/m)?.[1];
  expect(description?.length).toBeLessThanOrEqual(1024);
  expect(source).not.toContain("TODO");

  const references = await readdir(join(skillDir, "references"));
  expect(references.sort()).toEqual(expectedReferences);
  for (const reference of expectedReferences) {
    expect(source).toContain(`references/${reference}`);
  }
});

test("skill evaluations cover positive, negative, and unavailable-OpenAPI cases", async () => {
  const evaluation = JSON.parse(await readFile(evaluationFile, "utf8"));
  expect(evaluation.skill_name).toBe("eneo-flows-api");
  expect(evaluation.evals.length).toBeGreaterThanOrEqual(3);
  expect(
    evaluation.evals.every(
      (item) => item.expected_output && item.assertions.length >= 3,
    ),
  ).toBe(true);

  const triggerQueries = JSON.parse(
    await readFile(triggerQueriesFile, "utf8"),
  );
  expect(triggerQueries.length).toBeGreaterThanOrEqual(10);
  expect(triggerQueries.some((item) => item.should_trigger)).toBe(true);
  expect(triggerQueries.some((item) => !item.should_trigger)).toBe(true);
  expect(
    triggerQueries.some((item) => item.query.includes("openapi.json")),
  ).toBe(true);
});

test("the bundled TypeScript patterns parse", async () => {
  const source = await readFile(
    join(skillDir, "references", "typescript-patterns.md"),
    "utf8",
  );
  const blocks = [...source.matchAll(/^```ts\n([\s\S]*?)^```/gm)].map(
    (match) => match[1],
  );
  expect(blocks.length).toBeGreaterThanOrEqual(4);
  const parsed = ts.createSourceFile(
    "eneo-flows-api-patterns.ts",
    blocks.join("\n"),
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );
  expect(
    parsed.parseDiagnostics.map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, " "),
    ),
  ).toEqual([]);
});

test("the docs page publishes portable Codex and Claude Code installation", async () => {
  const source = await readFile(docsPage, "utf8");
  expect(source).toContain("/skills/eneo-flows-api.skill");
  expect(source).toContain("~/.codex/skills");
  expect(source).toContain("~/.claude/skills");
  expect(source).toContain("not an Eneo in-product Skill");
  await access(packageFile);
});

test("the published package exactly matches the reviewed skill sources", async () => {
  const process = Bun.spawn(["python3", packageScript, "--check"], {
    stdout: "pipe",
    stderr: "pipe",
  });
  const [exitCode, stdout, stderr] = await Promise.all([
    process.exited,
    new Response(process.stdout).text(),
    new Response(process.stderr).text(),
  ]);
  if (exitCode !== 0) throw new Error(stderr || stdout);
  expect(stdout).toContain("eneo-flows-api.skill matches its sources");
});
