// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { toast as sonner } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toaster } from "@/components/ui/sonner";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { TOAST_DURATION_MS, toast } from "./toast";

// Sonner adds toasts on a timer and removes them after an exit animation.
const settle = () => act(() => vi.advanceTimersByTimeAsync(300));

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  renderInApp(<Toaster theme="light" />);
});

afterEach(async () => {
  sonner.dismiss();
  await settle();
  cleanup();
  vi.useRealTimers();
});

describe("toast", () => {
  it("keeps errors and warnings until they are closed, and closes the rest after a while", async () => {
    toast.error("Namnet kunde inte sparas", { description: "Trace ID: 1234" });
    toast.warning("Fyll i alla obligatoriska fält");
    toast.success("Sparat");
    toast.info("Inget nytt att visa");
    await settle();
    expect(screen.getByText("Sparat")).toBeTruthy();

    await act(() => vi.advanceTimersByTimeAsync(TOAST_DURATION_MS + 1000));

    expect(screen.queryByText("Sparat")).toBeNull();
    expect(screen.queryByText("Inget nytt att visa")).toBeNull();
    expect(screen.getByText("Namnet kunde inte sparas")).toBeTruthy();
    expect(screen.getByText("Trace ID: 1234")).toBeTruthy();
    expect(screen.getByText("Fyll i alla obligatoriska fält")).toBeTruthy();
  });

  it("gives every toast a translated close button", async () => {
    toast.success("Sparat");
    toast.error("Namnet kunde inte sparas");
    await settle();

    const error = screen.getByText("Namnet kunde inte sparas").closest("li")!;
    const success = screen.getByText("Sparat").closest("li")!;
    expect(within(success).getByRole("button", { name: "Stäng aviseringen" })).toBeTruthy();
    await expectNoAxeViolations(document.body);

    fireEvent.click(within(error).getByRole("button", { name: "Stäng aviseringen" }));
    await settle();
    expect(screen.queryByText("Namnet kunde inte sparas")).toBeNull();
  });
});
