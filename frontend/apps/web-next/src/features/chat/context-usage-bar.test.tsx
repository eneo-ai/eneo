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
    assistantPromptTokens: 0,
    assistantAttachmentTokens: 0,
    skillContextTokens: 0,
    usedTokens,
    willExceedContext: false,
    ...overrides
  };
}

function renderMeter(value: ContextUsage) {
  return renderInApp(
    <ContextUsageBar
      pending={false}
      usage={value}
      modelName="Claude Haiku 4.5"
      cumulativeTokens={9_000}
      turnCount={2}
    />
  );
}

const meter = () => screen.queryByRole("button", { name: /^Kontextanvändning:/ });
const rendered = () => screen.queryByText(/Kontextanvändning/) !== null;
/** What the meter renders, inside the app's theme wrapper. */
const row = (container: HTMLElement) =>
  container.querySelector("[data-astryx-theme]")?.firstElementChild ?? null;

describe("ContextUsageBar", () => {
  it("shows the first question's baseline and the included Skill subset below the usual threshold", async () => {
    renderInApp(
      <ContextUsageBar
        pending={false}
        usage={usage(800, {
          lockedInputTokens: 0,
          pendingTextTokens: 0,
          assistantPromptTokens: 500,
          assistantAttachmentTokens: 300,
          skillContextTokens: 200
        })}
        cumulativeTokens={0}
        turnCount={0}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /^Kontextanvändning:/ }));
    const details = await screen.findByRole("dialog", { name: "Beräknad kontextanvändning" });
    expect(within(details).getByText("Assistentens fasta kontext")).toBeTruthy();
    expect(within(details).getByText("Assistentinstruktioner")).toBeTruthy();
    expect(within(details).getByText("Fasta bilagor")).toBeTruthy();
    expect(within(details).getByText("Varav skillkontext")).toBeTruthy();
    expect(within(details).getByText("200")).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Kontextanvändning:/ }).textContent).toMatch(
      /800 \/ 10.000/
    );
  });

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
        pending={false}
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

  it("keeps its place, without numbers, while the estimate for a new draft or model is on its way", () => {
    const shown = usage(SHOW_FROM_PERCENT * 100 + 500);
    const { container, rerender } = renderInApp(
      <ContextUsageBar pending={false} usage={shown} cumulativeTokens={9_000} turnCount={2} />
    );
    expect(meter()).toBeTruthy();
    // The new estimate is not there yet: the row stays, with no old figures in it.
    const waiting = usage(0, { lockedInputTokens: 0, pendingTextTokens: 0 });
    rerender(<ContextUsageBar usage={waiting} pending cumulativeTokens={9_000} turnCount={2} />);
    expect(meter()).toBeNull();
    expect(row(container)).not.toBeNull();
    expect(container.textContent).toBe("");
    // The answer came: the meter as before.
    rerender(
      <ContextUsageBar pending={false} usage={shown} cumulativeTokens={9_000} turnCount={2} />
    );
    expect(meter()).toBeTruthy();
    // No answer (an error, or nothing to estimate): as today, nothing.
    rerender(
      <ContextUsageBar pending={false} usage={waiting} cumulativeTokens={9_000} turnCount={2} />
    );
    expect(row(container)).toBeNull();
  });

  it("keeps its figures while a new estimate is on its way when the conversation already shows the row", () => {
    // 70 % of the window is the conversation so far: current, not an old estimate.
    const conversation = usage(7_000, { lockedInputTokens: 7_000, pendingTextTokens: 0 });
    const { rerender } = renderInApp(
      <ContextUsageBar
        pending={false}
        usage={conversation}
        cumulativeTokens={9_000}
        turnCount={2}
      />
    );
    rerender(
      <ContextUsageBar usage={conversation} pending cumulativeTokens={9_000} turnCount={2} />
    );
    expect(meter()?.textContent).toContain("70%");
  });

  it("does not appear for a new draft's estimate while the row was not shown", () => {
    const { container } = renderInApp(
      <ContextUsageBar usage={usage(500)} pending cumulativeTokens={9_000} turnCount={2} />
    );
    expect(row(container)).toBeNull();
  });

  it("renders nothing without a known window, pinned or not", () => {
    act(() => setContextUsagePinned(true));
    renderMeter(usage(500, { contextLimit: 0 }));
    expect(rendered()).toBe(false);
  });
});
