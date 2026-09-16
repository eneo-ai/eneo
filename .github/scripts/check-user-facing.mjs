#!/usr/bin/env node

// A pull request that changes what users see must say so in the PR
// template's "## User-facing" section (a sentence or "No"). Release notes are
// drafted from those sections, so an empty one is a gap in the next release's
// What's new page. See frontend/packages/whats-new/PLAYBOOK.md.
//
// Usage: check-user-facing.mjs --files <changed-files.txt> --body-file <pr-body.md> [--labels a,b]
// Exit 1 when a user-visible change has no filled-in section. A filled-in
// section without the `user-facing` label only warns (fork authors cannot
// label).

import assert from "node:assert/strict";
import fs from "node:fs";

if (process.argv.includes("--self-test")) {
  runSelfTest();
  process.exit(0);
}

const files = fs.readFileSync(getArgValue("--files"), "utf8").split("\n");
const body = fs.readFileSync(getArgValue("--body-file"), "utf8");
const labels = (getArgValue("--labels", "") || "")
  .split(",")
  .map((l) => l.trim())
  .filter(Boolean);

const result = evaluate({ files, body, labels });
for (const line of result.messages) console.log(line);
process.exit(result.ok ? 0 : 1);

export function evaluate({ files, body, labels }) {
  const touched = files
    .map((f) => f.trim())
    .filter(Boolean)
    .filter(isUserVisibleFile);
  const section = userFacingSection(body);
  const messages = [];

  if (touched.length === 0) {
    messages.push(
      "No user-visible files changed; User-facing section not required.",
    );
    return { ok: true, messages };
  }

  if (section === null) {
    messages.push(
      `::error::This PR changes user-visible files (${touched.slice(0, 3).join(", ")}${touched.length > 3 ? ", …" : ""}) but has no "## User-facing" section. ` +
        'Add it from the PR template with one or two sentences from the user\'s point of view, or "No".',
    );
    return { ok: false, messages };
  }
  if (section === "") {
    messages.push(
      `::error::"## User-facing" is empty but this PR changes user-visible files (${touched.slice(0, 3).join(", ")}${touched.length > 3 ? ", …" : ""}). ` +
        'Write one or two sentences from the user\'s point of view, or "No".',
    );
    return { ok: false, messages };
  }

  if (isNegative(section)) {
    messages.push("User-facing: No.");
    return { ok: true, messages };
  }

  messages.push(`User-facing: ${section.split("\n")[0]}`);
  if (!labels.includes("user-facing")) {
    messages.push(
      '::warning::Add the "user-facing" label so the release notes draft picks this PR up (see frontend/packages/whats-new/PLAYBOOK.md).',
    );
  }
  return { ok: true, messages };
}

function isUserVisibleFile(file) {
  const path = file.replaceAll("\\", "/").replace(/^\.\//, "");
  if (!path.startsWith("frontend/apps/web/")) return false;
  if (!(
    path.startsWith("frontend/apps/web/src/") ||
    path.startsWith("frontend/apps/web/messages/")
  ))
    return false;
  if (/\.(test|spec)\.[cm]?[jt]sx?$/.test(path)) return false;
  if (/(^|\/)(__screenshots__|__tests__|__mocks__)\//.test(path)) return false;
  if (path.startsWith("frontend/apps/web/src/lib/paraglide/")) return false;
  return true;
}

function userFacingSection(body) {
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

function isNegative(text) {
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

function runSelfTest() {
  const ui = ["frontend/apps/web/src/routes/(app)/account/+page.svelte"];
  const withSection = (text) =>
    `## Changes\nx\n\n## User-facing\n<!-- hint -->\n${text}\n\n## Testing\ny\n`;

  assert.equal(
    evaluate({ files: ["backend/src/eneo/x.py"], body: "", labels: [] }).ok,
    true,
  );
  assert.equal(
    evaluate({
      files: ["frontend/apps/web/src/lib/a.test.ts"],
      body: "",
      labels: [],
    }).ok,
    true,
  );
  assert.equal(
    evaluate({
      files: ["frontend/apps/web/package.json"],
      body: "",
      labels: [],
    }).ok,
    true,
  );

  assert.equal(
    evaluate({ files: ui, body: "## Changes\nx\n", labels: [] }).ok,
    false,
  );
  assert.equal(
    evaluate({ files: ui, body: withSection(""), labels: [] }).ok,
    false,
  );
  assert.equal(
    evaluate({ files: ui, body: withSection("No"), labels: [] }).ok,
    true,
  );
  assert.equal(
    evaluate({ files: ui, body: withSection("Nej."), labels: [] }).ok,
    true,
  );

  const filled = evaluate({
    files: ui,
    body: withSection("You can now change your password."),
    labels: [],
  });
  assert.equal(filled.ok, true);
  assert.ok(filled.messages.some((m) => m.includes("::warning::")));

  const labelled = evaluate({
    files: ui,
    body: withSection("You can now change your password."),
    labels: ["user-facing"],
  });
  assert.equal(labelled.ok, true);
  assert.ok(!labelled.messages.some((m) => m.includes("::warning::")));

  // Section last in the body, without a following heading.
  assert.equal(
    evaluate({ files: ui, body: "## User-facing\nNo\n", labels: [] }).ok,
    true,
  );
  assert.equal(
    userFacingSection("## User-facing\n<!-- c -->\n\n## Testing\n"),
    "",
  );

  console.log("check-user-facing self-test passed");
}
