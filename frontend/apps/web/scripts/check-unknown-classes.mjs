#!/usr/bin/env node
// Fails when a colour-style utility (bg-*, text-*, border-*, ring-*, …) names a token the
// theme does not define. Tailwind silently emits nothing for such classes, so a typo or a
// token name from another design system renders unstyled without any error.
//
// Candidates are extracted with Tailwind's own scanner and resolved against src/app.css.

import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { __unstable__loadDesignSystem } from "@tailwindcss/node";
import { Scanner } from "@tailwindcss/oxide";

const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const cssPath = resolve(appRoot, "src/app.css");

const COLOUR_UTILITY =
  /^(?:[a-z0-9-[\]&>*=_.:()@/]+:)*!?(?:bg|text|border(?:-[trblxyse])?|ring|outline|fill|stroke|divide|decoration|caret|placeholder|from|to|via)-[a-z][a-z0-9-]*(?:\/\d+)?!?$/;

// Words the scanner picks up that are not classes: SVG attributes and string identifiers.
const NOT_CLASSES = new Set([
  "stroke-width",
  "stroke-linecap",
  "stroke-linejoin",
  "fill-rule",
  "clip-rule",
  "text-field",
  "text-upload",
  "text-snippet",
  "text-completion-codestral",
  "text-completion-openai"
]);

const design = await __unstable__loadDesignSystem(readFileSync(cssPath, "utf8"), {
  base: dirname(cssPath)
});

const files = execFileSync("git", ["ls-files", "src/*.svelte", "src/*.ts"], {
  cwd: appRoot,
  encoding: "utf8"
})
  .split("\n")
  .filter((file) => file && !file.includes("/paraglide/") && !/\.(test|spec)\.ts$/.test(file))
  .filter((file) => existsSync(resolve(appRoot, file)));

const scanner = new Scanner({});
const problems = [];

for (const file of files) {
  const source = readFileSync(resolve(appRoot, file), "utf8");
  // Style blocks hold CSS properties and keyframe names, not utilities.
  const content = source.replace(/<style[\s\S]*?<\/style>/g, (block) => " ".repeat(block.length));
  const extension = file.split(".").pop();
  for (const { candidate, position } of scanner.getCandidatesWithPositions({
    content,
    extension
  })) {
    if (NOT_CLASSES.has(candidate) || !COLOUR_UTILITY.test(candidate)) continue;
    // An inline CSS declaration (`text-align: left`) is followed by a colon.
    if (/^\s*:/.test(content.slice(position + candidate.length))) continue;
    if (design.candidatesToCss([candidate])[0]) continue;
    const line = content.slice(0, position).split("\n").length;
    problems.push(`${file}:${line}  ${candidate}`);
  }
}

if (problems.length > 0) {
  console.error("Classes that resolve to no CSS (unknown colour token?):\n");
  for (const problem of problems) console.error(`  ${problem}`);
  console.error(
    "\nUse a token defined in packages/ui/src/styles or src/app.css (see frontend/COLORS.md)." +
      "\nIf the word is not a class, add it to NOT_CLASSES in scripts/check-unknown-classes.mjs."
  );
  process.exit(1);
}

console.log(`check-unknown-classes: ${files.length} files, no unknown colour classes.`);
