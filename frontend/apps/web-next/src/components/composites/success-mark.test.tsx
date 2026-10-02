// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SuccessMark } from "./success-mark";

afterEach(cleanup);

describe("SuccessMark", () => {
  it("is decorative and still at rest", () => {
    const { container } = render(<SuccessMark />);
    const mark = container.querySelector("[data-success-mark]");
    expect(mark?.getAttribute("aria-hidden")).toBe("true");
    expect(mark?.getAttribute("class")).not.toContain("animate-in");
  });

  it("pops in when given a replay key", () => {
    const { container } = render(<SuccessMark replayKey={1} size="sm" />);
    const mark = container.querySelector("[data-success-mark]");
    expect(mark?.getAttribute("class")).toContain("animate-in");
    expect(mark?.getAttribute("class")).toContain("size-4");
  });
});
