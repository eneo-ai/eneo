// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
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

describe("RunSteps step details", () => {
  it("says how a step read long material and which template it filled", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Skriv beslut", status: "completed" }]),
      [
        makeRunStep(1, {
          output_payload_json: {
            text: "Beslut",
            section_manifest: {
              character_length: 100,
              sections: [
                { core: { start_char: 0, end_char: 40 } },
                { core: { start_char: 40, end_char: 100 } }
              ]
            },
            template_provenance: { template_name: "Beslutsmall", published_flow_version: 4 }
          }
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.getByText("Läst del för del: 2 delar.")).toBeTruthy();
    expect(screen.getByText(/del 1: 0–40 %, del 2: 40–100 %/)).toBeTruthy();
    expect(screen.getByText(messages.flow_run_template_provenance_label)).toBeTruthy();
    expect(screen.getByText("Beslutsmall")).toBeTruthy();
  });

  it("keeps a failed step's rejected answer closed until asked for", () => {
    const steps = runStepViews(makeRunGraph([{ order: 1, label: "Svara", status: "failed" }]), [
      makeRunStep(1, {
        status: "failed",
        error_code: "typed_io_validation_failed",
        output_payload_json: { rejected_output: '{"svar": "fel form"}' }
      })
    ]);
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.queryByText(/fel form/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_rejected_output_title }));
    expect(screen.getByText(/fel form/)).toBeTruthy();
  });

  it("says how much text was read out of what was sent in, and its format", () => {
    const steps = runStepViews(makeRunGraph([{ order: 1, label: "Läs", status: "completed" }]), [
      makeRunStep(1, {
        input_payload_json: {
          runtime_input: { extracted_text_length: 1234, input_format: "document" }
        },
        runtime_input_file_ids: ["file-1"],
        runtime_input_files: [
          { file_id: "file-1", name: "ansökan.pdf", mimetype: "application/pdf" }
        ]
      })
    ]);
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.getByText(/Utläst text: 1\s234 tecken · Format: Dokument/)).toBeTruthy();
  });
});
