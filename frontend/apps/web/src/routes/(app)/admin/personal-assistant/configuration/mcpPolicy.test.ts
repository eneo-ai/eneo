import { describe, expect, test } from "vitest";
import { disabledToolIdsForSelectedServers } from "./mcpPolicy";

describe("disabledToolIdsForSelectedServers", () => {
  test("drops hidden tool denials when their server is deselected", () => {
    const visibleTool = { id: "visible" };
    const hiddenTool = { id: "hidden" };

    expect(
      disabledToolIdsForSelectedServers(
        [
          { id: "selected", tools: [visibleTool] },
          { id: "deselected", tools: [hiddenTool] }
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
