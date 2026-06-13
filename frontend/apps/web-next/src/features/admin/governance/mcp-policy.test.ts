import { describe, expect, test } from "vitest";
import { disabledToolIdsForSelectedServers } from "./mcp-policy";

describe("disabledToolIdsForSelectedServers", () => {
  test("drops hidden tool denials when their server is deselected", () => {
    expect(
      disabledToolIdsForSelectedServers(
        [
          { id: "selected", tools: [{ id: "visible" }] },
          { id: "deselected", tools: [{ id: "hidden" }] }
        ],
        ["selected"],
        ["visible", "hidden"]
      )
    ).toEqual(["visible"]);
  });

  test("preserves denials for hidden tools while their server remains selected", () => {
    expect(
      disabledToolIdsForSelectedServers(
        [{ id: "selected", tools: [{ id: "hidden" }] }],
        ["selected"],
        ["hidden"]
      )
    ).toEqual(["hidden"]);
  });
});
