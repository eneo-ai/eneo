// @vitest-environment jsdom
import { StrictMode } from "react";
import { act, cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import { FederationPending } from "./federation-pending";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("offers an explicit retry after ten seconds and clears its timer on unmount under StrictMode", () => {
  vi.useFakeTimers();
  const { unmount } = renderInApp(
    <StrictMode>
      <FederationPending href="/api/v1/auth/browser/initiate?tenant=first" />
    </StrictMode>
  );
  act(() => vi.advanceTimersByTime(9_999));
  expect(screen.queryByText(messages.connection_slow_warning)).toBeNull();
  act(() => vi.advanceTimersByTime(1));
  expect(screen.getByText(messages.connection_slow_warning)).toBeTruthy();
  expect(screen.getByRole("link", { name: messages.retry }).getAttribute("href")).toBe(
    "/api/v1/auth/browser/initiate?tenant=first"
  );
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

it("keeps the delayed warning and retry accessible", async () => {
  vi.useFakeTimers();
  const { container } = renderInApp(<FederationPending href="/api/v1/auth/browser/initiate" />);
  act(() => vi.advanceTimersByTime(10_000));
  vi.useRealTimers();
  await expectNoAxeViolations(container);
});
