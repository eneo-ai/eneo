// @vitest-environment jsdom
import { act, cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeRunGraph, makeRunStep } from "./run-fixtures";
import { RunLiveProgress } from "./run-live-progress";
import { runStepViews } from "./run-progress";
import { RunSteps } from "./run-steps";

vi.mock("@/lib/api/browser", () => ({ browserApi: {} }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("RunSteps", () => {
  it("splits each step's tokens into what went in and what came out", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1, { num_tokens_input: 1200, num_tokens_output: 300 })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    expect(within(card).getByText(/1\s500 token \(1\s200 in, 300 ut\)/)).toBeTruthy();
  });

  it("says what a running step does and which step is next in turn", async () => {
    const running = runStepViews(
      makeRunGraph([
        { order: 1, label: "Sammanfatta", status: "running" },
        { order: 2, label: "Skriv svar", status: "pending" }
      ]),
      []
    );
    const { container } = renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={running} />);
    expect(screen.getByText(messages.flow_run_progress_running_body)).toBeTruthy();
    expect(screen.queryByText(messages.flow_run_progress_next_step_hint)).toBeNull();
    await expectNoAxeViolations(container);
    cleanup();

    const waiting = runStepViews(
      makeRunGraph([
        { order: 1, label: "Sammanfatta", status: "completed" },
        { order: 2, label: "Skriv svar", status: "pending" }
      ]),
      []
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={waiting} />);
    const next = screen.getByRole("article", { name: "Steg 2: Skriv svar" });
    expect(within(next).getByText(messages.flow_run_progress_next_step_hint)).toBeTruthy();
  });
});

describe("RunLiveProgress", () => {
  const steps = runStepViews(
    makeRunGraph([
      { order: 1, label: "Sammanfatta", status: "completed" },
      { order: 2, label: "Skriv svar", status: "running" },
      { order: 3, label: "Skicka", status: "pending" }
    ]),
    []
  );

  it("counts the steps of a running run and its time, counted up each second", async () => {
    vi.useFakeTimers({ now: Date.parse("2026-10-21T08:01:00Z"), shouldAdvanceTime: true });
    const { container } = renderInApp(
      <RunLiveProgress
        summary={{ status: "running", started_at: "2026-10-21T08:00:00Z" }}
        steps={steps}
      />
    );
    expect(screen.getByText("Steg 2 av 3")).toBeTruthy();
    expect(screen.getByText(/Körs just nu/)).toBeTruthy();
    expect(
      screen.getByRole("progressbar", { name: messages.flow_run_journey_progress })
    ).toBeTruthy();
    expect(screen.getByText("Tid: 1 min 0 s")).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(screen.getByText("Tid: 1 min 5 s")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("is not shown once the run has ended", () => {
    renderInApp(
      <RunLiveProgress
        summary={{ status: "completed", started_at: "2026-10-21T08:00:00Z" }}
        steps={steps}
      />
    );
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});
