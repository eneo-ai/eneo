import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

const bunConfigs = ["frontend/bunfig.toml", "tool-runtime/bunfig.toml"];
const uvConfigs = ["backend/pyproject.toml", "tool-runtime/uv.toml"];

function bunCooldownDays(path) {
  const seconds = /^minimumReleaseAge = (\d+)$/m.exec(read(path))?.[1];
  assert.ok(seconds, `${path} sets minimumReleaseAge`);
  return Number(seconds) / 86400;
}

function uvCooldownDays(path) {
  const days = /^exclude-newer = "(\d+) days"$/m.exec(read(path))?.[1];
  assert.ok(days, `${path} sets exclude-newer as a number of days`);
  return Number(days);
}

function atLeast(version, minimum) {
  const [a, b] = [version, minimum].map((value) => value.split(".").map(Number));
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    if ((a[i] ?? 0) !== (b[i] ?? 0)) return (a[i] ?? 0) > (b[i] ?? 0);
  }
  return true;
}

test("npm and PyPI resolution wait the same number of days, at least a week", () => {
  const days = bunCooldownDays(bunConfigs[0]);
  assert.ok(days >= 7, `${bunConfigs[0]} waits ${days} days`);
  for (const path of bunConfigs) assert.equal(bunCooldownDays(path), days, path);
  for (const path of uvConfigs) assert.equal(uvCooldownDays(path), days, path);
});

test("an exception names one exact release, never a whole package", () => {
  for (const path of bunConfigs) {
    const list = /^minimumReleaseAgeExcludes = \[([^\]]*)\]/m.exec(read(path))?.[1] ?? "";
    for (const entry of list.match(/"[^"]*"/g) ?? []) {
      assert.match(entry, /^"(@[^/"@]+\/)?[^/"@]+@\d+\.\d+\.\d+[^"]*"$/, `${path}: ${entry}`);
    }
  }
  for (const path of uvConfigs) {
    const table = /^exclude-newer-package = \{([^}]*)\}/m.exec(read(path))?.[1] ?? "";
    assert.doesNotMatch(table, /=\s*false/, `${path} lifts the limit for a whole package`);
  }
});

test("every pinned uv meets the version the relative exclude-newer requires", () => {
  const minimum = /^required-version = ">=([\d.]+)"$/m.exec(read("backend/pyproject.toml"))?.[1];
  assert.ok(minimum, "backend/pyproject.toml sets required-version");

  const pins = [];
  for (const file of readdirSync(new URL(".github/workflows/", root))) {
    const path = `.github/workflows/${file}`;
    for (const match of read(path).matchAll(/setup-uv@[^\n]*\n\s+with:\n\s+version: "([\d.]+)"/g)) {
      pins.push([path, match[1]]);
    }
  }
  const hook = /uv-pre-commit\n\s+rev: ([\d.]+)/.exec(read(".pre-commit-config.yaml"))?.[1];
  assert.ok(hook, ".pre-commit-config.yaml pins uv-pre-commit");
  pins.push([".pre-commit-config.yaml", hook]);

  assert.ok(pins.length > 1, "found the workflow pins");
  for (const [path, version] of pins) {
    assert.ok(atLeast(version, minimum), `${path} pins uv ${version}, below ${minimum}`);
  }
});
