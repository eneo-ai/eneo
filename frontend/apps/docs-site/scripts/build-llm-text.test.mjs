/**
 * Guards the two things the Markdown mirror exists to get right: it must strip
 * MDX plumbing from prose, and it must leave fenced examples exactly alone.
 *
 * The guides publish complete client listings whose own `import` and `export`
 * lines are indistinguishable from the MDX component imports the flattener
 * removes, so a regex applied to the whole document silently mutilates them.
 */
import { test, expect, afterEach } from "bun:test";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

import {
  FLOWS_BUNDLE_ROUTES,
  buildLlmText,
  flattenMdx,
} from "./build-llm-text.mjs";

const appDir = dirname(dirname(fileURLToPath(import.meta.url)));
const integratingGuide = join(
  appDir,
  "src",
  "content",
  "guides",
  "flows",
  "integrating-flows.mdx",
);

test("flattenMdx removes MDX imports from prose", () => {
  const flattened = flattenMdx(
    'import { Callout } from "nextra/components";\n\n# Title\n',
  );
  expect(flattened).toBe("# Title");
});

test("flattenMdx leaves import and export inside a fence untouched", () => {
  const source = [
    'import { Callout } from "nextra/components";',
    "",
    "# Title",
    "",
    "```ts",
    'import { readFile } from "node:fs/promises";',
    "export type Status = 'queued' | 'running';",
    "export class Client {}",
    "```",
    "",
  ].join("\n");

  const flattened = flattenMdx(source);

  expect(flattened).not.toContain('from "nextra/components"');
  expect(flattened).toContain('import { readFile } from "node:fs/promises";');
  expect(flattened).toContain("export type Status = 'queued' | 'running';");
  expect(flattened).toContain("export class Client {}");
});

test("flattenMdx keeps every exported declaration of the published client", async () => {
  const source = await readFile(integratingGuide, "utf8");
  const exported = (line) => /^export\s/.test(line);
  const inFence = (text) =>
    text.split("\n").reduce(
      (state, line) =>
        /^\s*```/.test(line)
          ? { open: !state.open, lines: state.lines }
          : {
              open: state.open,
              lines: state.open ? [...state.lines, line] : state.lines,
            },
      { open: false, lines: [] },
    ).lines;

  const before = inFence(source).filter(exported).length;
  const after = inFence(flattenMdx(source)).filter(exported).length;

  expect(before).toBeGreaterThan(0);
  expect(after).toBe(before);
});

test("the published TypeScript client parses without syntax errors", async () => {
  const source = await readFile(integratingGuide, "utf8");
  const blocks = [...source.matchAll(/^```ts\n([\s\S]*?)^```/gm)].map(
    (m) => m[1],
  );
  expect(blocks).toHaveLength(1);

  const parsed = ts.createSourceFile(
    "client.ts",
    blocks[0],
    ts.ScriptTarget.ES2022,
    true,
    ts.ScriptKind.TS,
  );

  expect(
    parsed.parseDiagnostics.map((d) =>
      ts.flattenDiagnosticMessageText(d.messageText, " "),
    ),
  ).toEqual([]);
});

test("the polling example contains only the content-free run summary", async () => {
  const source = await readFile(integratingGuide, "utf8");
  const section = source.match(/### 4\. Poll run[\s\S]*?(?=\n### 5\.)/)?.[0];
  expect(section).toBeDefined();

  const responseBlock = section?.match(/^```json\n([\s\S]*?)^```/m)?.[1];
  expect(responseBlock).toBeDefined();
  const response = JSON.parse(responseBlock);

  expect(response.status).toBe("awaiting_review");
  for (const contentField of [
    "error",
    "input_payload_json",
    "result",
    "result_files",
    "token_usage",
    "transcription_usage",
    "webhook_deliveries",
  ]) {
    expect(response).not.toHaveProperty(contentField);
  }
});

test("every route in the Flows bundle exists as content", async () => {
  const { FLOWS_BUNDLE_ROUTES } = await import("./build-llm-text.mjs");
  const { access } = await import("node:fs/promises");
  for (const route of FLOWS_BUNDLE_ROUTES) {
    const candidates = [
      join(appDir, "src", "content", `${route}.mdx`),
      join(appDir, "src", "content", route, "index.mdx"),
    ];
    let found = false;
    for (const candidate of candidates) {
      try {
        await access(candidate);
        found = true;
        break;
      } catch {}
    }
    expect(found, route).toBe(true);
  }
});

// build-versions builds every release line with this script and that line's own
// content. Content from before Flows has none of the bundle's pages; content
// with only some of them means the route list and the pages have drifted apart.
const fixtureApps = [];
afterEach(async () => {
  await Promise.all(
    fixtureApps
      .splice(0)
      .map((app) => rm(app, { recursive: true, force: true })),
  );
});

async function appWithPages(routes) {
  const app = await mkdtemp(join(tmpdir(), "eneo-llm-text-"));
  fixtureApps.push(app);
  for (const route of routes) {
    const file = join(app, "src", "content", `${route || "index"}.mdx`);
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, `# ${route || "Eneo"}\n\nAbout ${route}.\n`, "utf8");
  }
  return app;
}

test("content without Flows pages builds without the Flows bundle", async () => {
  const app = await appWithPages(["", "guides/deployment"]);

  await buildLlmText(app);

  expect(existsSync(join(app, "out", "llms-flows.txt"))).toBe(false);
  expect(await readFile(join(app, "out", "llms-full.txt"), "utf8")).toContain(
    "About guides/deployment.",
  );
  const index = await readFile(join(app, "out", "llms.txt"), "utf8");
  expect(index).toContain("/guides/deployment.md");
  expect(index).not.toContain("Flows");
});

test("content with every Flows page gets the bundle in reading order", async () => {
  const app = await appWithPages(["", ...FLOWS_BUNDLE_ROUTES]);

  await buildLlmText(app);

  const bundle = await readFile(join(app, "out", "llms-flows.txt"), "utf8");
  expect(
    [...bundle.matchAll(/^<!-- source: \/(.+)\.md -->$/gm)].map((m) => m[1]),
  ).toEqual(FLOWS_BUNDLE_ROUTES);
  expect(await readFile(join(app, "out", "llms.txt"), "utf8")).toContain(
    "/llms-flows.txt",
  );
});

test("content with only some Flows pages fails and names the missing ones", async () => {
  const app = await appWithPages(FLOWS_BUNDLE_ROUTES.slice(0, -1));

  await expect(buildLlmText(app)).rejects.toThrow(
    `llms-flows.txt lists routes that do not exist: ${FLOWS_BUNDLE_ROUTES.at(-1)}`,
  );
});
