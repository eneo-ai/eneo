/**
 * Guards the two things the Markdown mirror exists to get right: it must strip
 * MDX plumbing from prose, and it must leave fenced examples exactly alone.
 *
 * The guides publish complete client listings whose own `import` and `export`
 * lines are indistinguishable from the MDX component imports the flattener
 * removes, so a regex applied to the whole document silently mutilates them.
 */
import { test, expect } from "bun:test";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

import { flattenMdx } from "./build-llm-text.mjs";

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
