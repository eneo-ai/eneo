import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ALWAYS_LOGGED_ACTIONS } from "./always-logged-actions";

const backend = (path: string) =>
  readFileSync(
    fileURLToPath(new URL(`../../../../../../../../backend/src/eneo/${path}`, import.meta.url)),
    "utf8"
  );

/** `ActionType.NAME` → its value, as action_types.py declares them. */
const ACTION_VALUES = new Map(
  [...backend("audit/domain/action_types.py").matchAll(/^ {4}([A-Z_]+) = "([a-z_]+)"$/gm)].map(
    ([, name, value]) => [name, value]
  )
);

const MANDATORY_NAMES = [
  .../^MANDATORY_AUDIT_ACTIONS[^=]*= frozenset\(\s*\{([\s\S]*?)\}\s*\)/m
    .exec(backend("audit/domain/mandatory_actions.py"))![1]
    .matchAll(/ActionType\.([A-Z_]+)/g)
].map(([, name]) => name);

describe("always-logged audit actions", () => {
  it("are exactly the backend's mandatory actions", () => {
    expect(MANDATORY_NAMES.length).toBeGreaterThan(0);
    const mandatory = MANDATORY_NAMES.map((name) => ACTION_VALUES.get(name));
    expect(mandatory).not.toContain(undefined);
    expect([...ALWAYS_LOGGED_ACTIONS].sort()).toEqual([...mandatory].sort());
  });
});
