import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const aiBuilderDir = fileURLToPath(new URL(".", import.meta.url));
const sourceExtensions = new Set([".svelte", ".ts"]);
const forbiddenImports = [
  /@xyflow\/svelte/,
  /\bdagre\b/,
  /FlowGraph\.svelte/,
  /\bdraftSpecToFlow\b/,
  /\bplanStepsToFlowSteps\b/
];

function listSourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    const stats = statSync(path);

    if (stats.isDirectory()) {
      return listSourceFiles(path);
    }

    if (entry.endsWith(".test.ts")) {
      return [];
    }

    if (![...sourceExtensions].some((extension) => entry.endsWith(extension))) {
      return [];
    }

    return [path];
  });
}

describe("FlowAIBuilderCanvas import boundary", () => {
  it("keeps the builder plan preview independent from the editor graph stack", () => {
    // This is a direct-source fence; full route-bundle analysis belongs in the build gate.
    const violations = listSourceFiles(aiBuilderDir).flatMap((path) => {
      const source = readFileSync(path, "utf8");

      return forbiddenImports
        .filter((pattern) => pattern.test(source))
        .map((pattern) => ({
          file: relative(aiBuilderDir, path),
          pattern: pattern.source
        }));
    });

    expect(violations).toEqual([]);
  });
});
