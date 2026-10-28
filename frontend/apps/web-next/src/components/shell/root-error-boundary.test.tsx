// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { RootErrorBoundary } from "./root-error-boundary";

afterEach(() => vi.restoreAllMocks());

it("renders recovery without any providers when a child crashes", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  function Broken(): never {
    throw new Error("Provider failed");
  }
  const { container } = render(
    <RootErrorBoundary>
      <Broken />
    </RootErrorBoundary>
  );
  expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  expect(screen.getByRole("main").lang).toBe("en");
  await expectNoAxeViolations(container);
});
