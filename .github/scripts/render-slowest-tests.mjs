#!/usr/bin/env node
// Renders the slowest tests from a pytest --junitxml report as a markdown
// table (stdout), for $GITHUB_STEP_SUMMARY. Usage:
//   node render-slowest-tests.mjs <junit.xml> [--top N]
//   node render-slowest-tests.mjs --self-test

import { readFileSync } from "node:fs";

export function slowestTests(xml, top = 20) {
  const tests = [];
  const testcaseRe = /<testcase\b[^>]*>/g;
  for (const match of xml.match(testcaseRe) ?? []) {
    const attr = (name) => {
      const m = match.match(new RegExp(`[\\s<]${name}="([^"]*)"`));
      return m ? m[1] : "";
    };
    const time = Number.parseFloat(attr("time"));
    if (Number.isFinite(time)) {
      tests.push({
        name: `${attr("classname")}::${attr("name")}`,
        time,
      });
    }
  }
  tests.sort((a, b) => b.time - a.time);
  return tests.slice(0, top);
}

export function renderMarkdown(tests, title) {
  const lines = [`### ${title}`, "", "| # | Test | Seconds |", "|---|---|---|"];
  tests.forEach((t, i) => {
    lines.push(`| ${i + 1} | \`${t.name}\` | ${t.time.toFixed(2)} |`);
  });
  if (tests.length === 0) lines.push("| - | _no testcases found_ | - |");
  return lines.join("\n");
}

function selfTest() {
  const xml = `
    <testsuite>
      <testcase classname="tests.a" name="test_fast" time="0.010"/>
      <testcase classname="tests.b" name="test_slow" time="3.500"/>
      <testcase classname="tests.c" name="test_mid" time="1.200"/>
      <testcase classname="tests.d" name="test_skipped"><skipped/></testcase>
    </testsuite>`;
  const ranked = slowestTests(xml, 2);
  const ok =
    ranked.length === 2 &&
    ranked[0].name === "tests.b::test_slow" &&
    ranked[1].name === "tests.c::test_mid" &&
    renderMarkdown(ranked, "t").includes("| 1 | `tests.b::test_slow` | 3.50 |");
  if (!ok) {
    console.error("render-slowest-tests self-test FAILED");
    process.exit(1);
  }
  console.log("render-slowest-tests self-test OK");
}

const args = process.argv.slice(2);
if (args.includes("--self-test")) {
  selfTest();
} else {
  const file = args.find((a) => !a.startsWith("--"));
  if (!file) {
    console.error("usage: render-slowest-tests.mjs <junit.xml> [--top N]");
    process.exit(2);
  }
  const topIdx = args.indexOf("--top");
  const top = topIdx === -1 ? 20 : Number.parseInt(args[topIdx + 1], 10);
  const xml = readFileSync(file, "utf8");
  console.log(renderMarkdown(slowestTests(xml, top), `Slowest tests (${file})`));
}
