// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { HydrationMark } from "./hydration-mark";

afterEach(() => {
  delete document.documentElement.dataset.hydrated;
});

it("marks <html> once mounted, for the e2e fixture to wait on", () => {
  expect(document.documentElement.hasAttribute("data-hydrated")).toBe(false);

  render(<HydrationMark />);

  expect(document.documentElement.hasAttribute("data-hydrated")).toBe(true);
});
