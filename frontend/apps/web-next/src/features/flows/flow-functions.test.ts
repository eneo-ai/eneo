import { describe, expect, it } from "vitest";
import { functionsFixture } from "./flow-fixtures";
import { functionAvailability, toolArgumentNames, toolArgumentSkeleton } from "./flow-functions";

describe("functionAvailability", () => {
  it("tells whether a function step can run as it is, and why not", () => {
    expect(
      functionAvailability(functionsFixture, { purpose: "charts", tool: "render_chart" })
    ).toBe("ok");
    expect(functionAvailability(functionsFixture, { purpose: "charts", tool: "nope" })).toBe(
      "unknown_tool"
    );
    expect(functionAvailability(functionsFixture, { purpose: "compute", tool: "run" })).toBe(
      "unavailable"
    );
    expect(functionAvailability(functionsFixture, { purpose: "web_search", tool: "search" })).toBe(
      "disabled"
    );
    expect(functionAvailability(undefined, { purpose: "charts", tool: "render_chart" })).toBe(
      "unknown"
    );
  });
});

describe("tool arguments", () => {
  it("lists a tool's arguments with the required ones first and starred", () => {
    const tool = functionsFixture[4]!.tools![0]!;
    expect(toolArgumentNames(tool)).toEqual(["data*", "kind"]);
    expect(toolArgumentSkeleton(tool)).toEqual({ data: "" });
    expect(toolArgumentNames(functionsFixture[4]!.tools![1]!)).toEqual([]);
    expect(toolArgumentNames(null)).toEqual([]);
  });
});
