// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { renderInApp } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { RouteError } from "./route-error";

const toast = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast }));
const writeText = vi.fn<(_: string) => Promise<void>>();
const error = new EneoApiError("Refused", { status: 500, errorId: "error-1", traceId: "trace-1" });
beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  writeText.mockResolvedValue(undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.resetAllMocks();
});

it("copies support references and links to the existing session logout route", async () => {
  const { container } = renderInApp(<RouteError error={error} reset={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Kopiera" }));
  await waitFor(() =>
    expect(writeText).toHaveBeenCalledWith("Fel-ID: error-1\nSpårnings-ID: trace-1")
  );
  expect(screen.getByRole("link", { name: "radera dina cookies." }).getAttribute("href")).toBe(
    "/logout"
  );
  await expectNoAxeViolations(container);
});

it("keeps references available for manual copying when the clipboard refuses", async () => {
  writeText.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
  renderInApp(<RouteError error={error} reset={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Kopiera" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledOnce());
  expect(screen.getByText("Fel-ID: error-1")).toBeTruthy();
  expect(screen.getByText("Spårnings-ID: trace-1")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Kopiera" }).hasAttribute("disabled")).toBe(false);
});

it("does not offer an empty copy action for a render error without references", () => {
  renderInApp(<RouteError error={new Error("render failed")} reset={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "Kopiera" })).toBeNull();
  expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
});
