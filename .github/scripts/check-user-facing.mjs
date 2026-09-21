#!/usr/bin/env node

// Every pull request must say what changes for users in the PR template's
// "## User-facing" section: one or two sentences from the user's point of
// view, or "No". Release notes are drafted from those sections
// (scripts/collect_user_facing.mjs), so a missing one is a gap in the next
// release's What's new page — and only the author knows whether a backend
// change is something users notice. Bot authors (dependency updates) are
// exempt. See frontend/packages/whats-new/PLAYBOOK.md.
//
// Usage: check-user-facing.mjs --body-file <pr-body.md> [--author-type User|Bot]
// Exit 1 when the section is missing or empty.

import assert from "node:assert/strict";
import fs from "node:fs";
import { pathToFileURL } from "node:url";

export function evaluate({ body, authorType }) {
  const messages = [];
  if (authorType === "Bot") {
    messages.push("Bot author; User-facing section not required.");
    return { ok: true, messages };
  }

  const section = userFacingSection(body);
  if (section === null) {
    messages.push(
      '::error::This PR has no "## User-facing" section. Add it from the PR template ' +
        'with one or two sentences from the user\'s point of view, or "No" — ' +
        "release notes are drafted from it (frontend/packages/whats-new/PLAYBOOK.md).",
    );
    return { ok: false, messages };
  }
  if (section === "") {
    messages.push(
      '::error::"## User-facing" is empty. Write one or two sentences from the ' +
        'user\'s point of view, or "No" — release notes are drafted from it ' +
        "(frontend/packages/whats-new/PLAYBOOK.md).",
    );
    return { ok: false, messages };
  }

  if (isNegative(section)) {
    messages.push("User-facing: No.");
    return { ok: true, messages };
  }

  messages.push(`User-facing: ${section.split("\n")[0]}`);
  return { ok: true, messages };
}

/** The trimmed text of "## User-facing"; "" when empty, null when absent. */
export function userFacingSection(body) {
  const match =
    /^##\s+User-facing\s*$([\s\S]*?)(?=^##\s|\s*$(?![\s\S]))/im.exec(
      body ?? "",
    );
  if (!match) return null;
  return match[1]
    .replace(/<!--[\s\S]*?-->/g, "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");
}

export function isNegative(text) {
  return /^(no|nej|none|n\/a|nothing)[.!]?$/i.test(text.trim());
}

function getArgValue(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) {
    if (fallback !== undefined) return fallback;
    throw new Error(`${name} is required`);
  }
  const value = process.argv[index + 1];
  if (value === undefined || value.startsWith("--"))
    throw new Error(`${name} requires a value`);
  return value;
}

function main() {
  if (process.argv.includes("--self-test")) {
    runSelfTest();
    return 0;
  }
  const body = fs.readFileSync(getArgValue("--body-file"), "utf8");
  const authorType = getArgValue("--author-type", "User");
  const result = evaluate({ body, authorType });
  for (const line of result.messages) console.log(line);
  return result.ok ? 0 : 1;
}

function runSelfTest() {
  const withSection = (text) =>
    `## Changes\nx\n\n## User-facing\n<!-- hint -->\n${text}\n\n## Testing\ny\n`;

  // The rule does not depend on which files changed: a backend-only fix that
  // users notice must be described too.
  assert.equal(evaluate({ body: "## Changes\nx\n" }).ok, false);
  assert.equal(evaluate({ body: "" }).ok, false);
  assert.equal(evaluate({ body: withSection("") }).ok, false);
  assert.equal(evaluate({ body: withSection("No") }).ok, true);
  assert.equal(evaluate({ body: withSection("Nej.") }).ok, true);

  const filled = evaluate({ body: withSection("You can now change your password.") });
  assert.equal(filled.ok, true);
  assert.deepEqual(filled.messages, [
    "User-facing: You can now change your password.",
  ]);

  // Dependency bots do not fill in the template.
  assert.equal(evaluate({ body: "", authorType: "Bot" }).ok, true);
  assert.equal(evaluate({ body: withSection(""), authorType: "User" }).ok, false);

  // Section last in the body, without a following heading.
  assert.equal(evaluate({ body: "## User-facing\nNo\n" }).ok, true);
  assert.equal(userFacingSection("## User-facing\n<!-- c -->\n\n## Testing\n"), "");
  assert.equal(userFacingSection("## Changes\nx\n"), null);
  assert.equal(isNegative(" n/a "), true);
  assert.equal(isNegative("No, but…"), false);

  console.log("check-user-facing self-test passed");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main());
}
