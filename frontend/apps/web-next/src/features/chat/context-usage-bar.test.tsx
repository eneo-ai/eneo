// @vitest-environment jsdom
/**
 * The context meter under the composer (UX review B4): nothing below 60 % of
 * the window, the meter from there (or when the estimate overflows), and
 * always when the user pinned it from the chat menu.
 */
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ContextUsage } from "@/lib/chat/use-preflight";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ContextUsageBar, SHOW_FROM_PERCENT, setContextUsagePinned } from "./context-usage-bar";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function usage(usedTokens: number, overrides: Partial<ContextUsage> = {}): ContextUsage {
  return {
    contextLimit: 10_000,
    lockedInputTokens: Math.max(0, usedTokens - 200),
    lockedOutputTokens: 0,
    pendingTextTokens: Math.min(200, usedTokens),
    pendingFileTokens: 0,
    usedTokens,
    willExceedContext: false,
    ...overrides
  };
}

function renderMeter(value: ContextUsage) {
  return renderInApp(
    <ContextUsageBar
      usage={value}
      modelName="Claude Haiku 4.5"
      cumulativeTokens={9_000}
      turnCount={2}
    />
  );
}

const meter = () => screen.queryByRole("button", { name: /^Kontextanvändning:/ });
const rendered = () => screen.queryByText(/Kontextanvändning/) !== null;

describe("ContextUsageBar", () => {
  it("renders nothing while the window has room", () => {
    renderMeter(usage(5_900));
    expect(SHOW_FROM_PERCENT).toBe(60);
    expect(meter()).toBeNull();
    expect(rendered()).toBe(false);
  });

  it("appears from 60 % of the window and when the estimate overflows", () => {
    const { rerender } = renderMeter(usage(6_000));
    expect(meter()).toBeTruthy();

    rerender(
      <ContextUsageBar
        usage={usage(10_500, { willExceedContext: true })}
        cumulativeTokens={0}
        turnCount={0}
      />
    );
    // sv-SE groups thousands with a narrow no-break space.
    expect(meter()?.textContent).toMatch(/10.500 \/ 10.000/);
  });

  it("explains the estimate in a popover and cannot be hidden while it warns", async () => {
    renderMeter(usage(7_700));
    fireEvent.click(meter()!);
    const popover = await screen.findByRole("dialog", { name: "Beräknad kontextanvändning" });
    expect(within(popover).getByText("Ditt meddelande")).toBeTruthy();
    expect(within(popover).getByText("Claude Haiku 4.5")).toBeTruthy();
    expect(within(popover).queryByRole("button", { name: "Dölj kontextanvändning" })).toBeNull();
    await expectNoAxeViolations(popover);
  });

  it("shows below the threshold once pinned from the chat menu, and the popover unpins it", async () => {
    renderMeter(usage(1_200));
    expect(meter()).toBeNull();

    act(() => setContextUsagePinned(true));
    const bar = await screen.findByRole("button", { name: /^Kontextanvändning:/ });
    expect(bar.textContent).toContain("12%");

    fireEvent.click(bar);
    const popover = await screen.findByRole("dialog", { name: "Beräknad kontextanvändning" });
    fireEvent.click(within(popover).getByRole("button", { name: "Dölj kontextanvändning" }));
    await waitFor(() => expect(meter()).toBeNull());
    expect(window.localStorage.getItem("contextUsageBarPinned")).toBe("false");
  });

  it("renders nothing without a known window, pinned or not", () => {
    act(() => setContextUsagePinned(true));
    renderMeter(usage(500, { contextLimit: 0 }));
    expect(rendered()).toBe(false);
  });
});
