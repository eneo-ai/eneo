import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type { FlowStep } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowDraftCheck from "./FlowDraftCheck.svelte";

afterEach(() => {
  cleanup();
});

function step(order: number): FlowStep {
  return { id: `step-${order}`, step_order: order, assistant_id: `assistant-${order}` } as FlowStep;
}

function props(overrides: Partial<Parameters<typeof render<typeof FlowDraftCheck>>[1]> = {}) {
  return {
    steps: [step(1), step(2)],
    issueCount: 0,
    saveStatus: "saved" as const,
    draftRevision: 3,
    onCheck: vi.fn(async () => {}),
    ...overrides
  };
}

describe("FlowDraftCheck", () => {
  it("cannot claim success for an empty flow", () => {
    render(FlowDraftCheck, props({ steps: [] }));

    expect(
      (screen.getByRole("button", { name: m.flow_check_flow() }) as HTMLButtonElement).disabled
    ).toBe(true);
    expect(screen.getByText(m.flow_check_empty())).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("flushes saves through onCheck and reports no known issues without running the flow", async () => {
    const onCheck = vi.fn(async () => {});
    render(FlowDraftCheck, props({ onCheck }));

    await fireEvent.click(screen.getByRole("button", { name: m.flow_check_flow() }));

    await waitFor(() => expect(onCheck).toHaveBeenCalledTimes(1));
    expect((await screen.findByRole("status")).textContent).toContain(m.flow_check_result_clean());
  });

  it("shows the editor's issues after a check and offers to reveal them", async () => {
    const onShowIssues = vi.fn();
    render(FlowDraftCheck, props({ issueCount: 2, onShowIssues }));

    await fireEvent.click(screen.getByRole("button", { name: m.flow_check_flow() }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(m.flow_check_result_issues({ count: "2" }));
    await fireEvent.click(screen.getByRole("button", { name: m.flow_check_show_issues() }));
    expect(onShowIssues).toHaveBeenCalledTimes(1);
  });

  it("invalidates a clean result when the draft changes or a save is pending", async () => {
    const { rerender } = render(FlowDraftCheck, props());
    await fireEvent.click(screen.getByRole("button", { name: m.flow_check_flow() }));
    expect((await screen.findByRole("status")).textContent).toContain(m.flow_check_result_clean());

    await rerender(props({ saveStatus: "unsaved" }));
    expect(screen.getByRole("status").textContent).toContain(m.flow_check_result_stale());

    await rerender(props({ saveStatus: "saved", draftRevision: 4 }));
    expect(screen.getByRole("status").textContent).toContain(m.flow_check_result_stale());
  });

  it("reports a save that could not complete instead of a result", async () => {
    const onCheck = vi.fn(async () => {
      throw new Error("network");
    });
    render(FlowDraftCheck, props({ onCheck }));

    await fireEvent.click(screen.getByRole("button", { name: m.flow_check_flow() }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      m.flow_check_result_save_failed()
    );
    expect(screen.queryByRole("status")).toBeNull();
  });
});
