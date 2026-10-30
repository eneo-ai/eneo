// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeRunGraph, makeRunStep } from "./run-fixtures";
import { RunLiveProgress } from "./run-live-progress";
import { runStepViews } from "./run-progress";
import { RunSteps } from "./run-steps";
import { runKeys, type RunEvidence } from "./runs-api";

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

  it("says when a step that ran has no recorded token usage", () => {
    const steps = runStepViews(
      makeRunGraph([
        { order: 1, label: "Sammanfatta", status: "completed" },
        { order: 2, label: "Skriv svar", status: "running" }
      ]),
      [
        makeRunStep(1, { num_tokens_input: null, num_tokens_output: null }),
        makeRunStep(2, {
          status: "running",
          finished_at: null,
          num_tokens_input: null,
          num_tokens_output: null
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const first = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    expect(
      within(first).getByText(new RegExp(messages.flow_run_token_usage_not_recorded))
    ).toBeTruthy();
    const second = screen.getByRole("article", { name: "Steg 2: Skriv svar" });
    expect(
      within(second).queryByText(new RegExp(messages.flow_run_token_usage_not_recorded))
    ).toBeNull();
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

describe("RunSteps output", () => {
  it("keeps secondary output collapsed until opened and retains focus on its trigger", async () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1)]
    );
    const { container } = renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    expect(within(card).queryByText("Resultat från steg 1")).toBeNull();
    const trigger = within(card).getByRole("button", { name: messages.flow_runs_step_output });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(
      within(card).getByRole("button", { name: messages.flow_run_more_copy_output })
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    trigger.focus();
    fireEvent.click(trigger);
    expect(await within(card).findByText("Resultat från steg 1")).toBeTruthy();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    await expectNoAxeViolations(container);

    fireEvent.click(trigger);
    expect(within(card).queryByText("Resultat från steg 1")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("renders a step's text as Markdown and keeps its line breaks", async () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [
        makeRunStep(1, {
          output_payload_json: {
            text: "## Beslut\n\nAnsökan **beviljas**.\n\n- Bygglov\n- Marklov\n\nTalare 1: Hej\nTalare 2: Hej igen"
          }
        })
      ]
    );
    const { container } = renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_runs_step_output }));
    expect(await within(card).findByRole("heading", { name: "Beslut" })).toBeTruthy();
    expect(within(card).getByText("beviljas").outerHTML).toMatch(/strong/);
    expect(
      within(card)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["Bygglov", "Marklov"]);
    // Lines written one under the other stay that way.
    const lines = within(card).getByText(/Talare 1: Hej/);
    expect(lines.tagName).toBe("P");
    expect(lines.textContent).toBe("Talare 1: Hej\nTalare 2: Hej igen");
    expect(lines.closest(".eneo-answer")?.className).toContain("[&_p]:whitespace-pre-line");
    await expectNoAxeViolations(container);
  });
});

describe("RunSteps copying", () => {
  it("copies a step's output, its structured value as JSON", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const steps = runStepViews(
      makeRunGraph([
        { order: 1, label: "Sammanfatta", status: "completed" },
        { order: 2, label: "Fält", status: "completed" }
      ]),
      [
        makeRunStep(1),
        makeRunStep(2, { output_payload_json: { structured: { mottagare: "Anna" } } })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const first = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    fireEvent.click(
      within(first).getByRole("button", { name: messages.flow_run_more_copy_output })
    );
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Resultat från steg 1"));

    const second = screen.getByRole("article", { name: "Steg 2: Fält" });
    fireEvent.click(
      within(second).getByRole("button", { name: messages.flow_run_more_copy_output })
    );
    await waitFor(() =>
      expect(writeText).toHaveBeenLastCalledWith(JSON.stringify({ mottagare: "Anna" }, null, 2))
    );
  });

  it("copies what a step was sent", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1, { input_payload_json: { text: "Ärendet gäller bygglov." } })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_runs_step_input }));
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_more_copy_input }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        JSON.stringify({ text: "Ärendet gäller bygglov." }, null, 2)
      )
    );
  });

  it("renders what a step was sent only while it is open", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1, { input_payload_json: { text: "Ärendet gäller bygglov." } })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    const trigger = within(card).getByRole("button", { name: messages.flow_runs_step_input });
    expect(card.textContent).not.toContain("Ärendet gäller bygglov.");
    expect(
      within(card).queryByRole("button", { name: messages.flow_run_more_copy_input })
    ).toBeNull();

    fireEvent.click(trigger);
    expect(card.textContent).toContain("Ärendet gäller bygglov.");
    fireEvent.click(trigger);
    expect(card.textContent).not.toContain("Ärendet gäller bygglov.");
    fireEvent.click(trigger);
    expect(card.textContent).toContain("Ärendet gäller bygglov.");
    expect(
      within(card).getByRole("button", { name: messages.flow_run_more_copy_input })
    ).toBeTruthy();
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

describe("RunSteps after a failure", () => {
  it("says the steps after the failed one did not run, and keeps the error on the failed one", async () => {
    const steps = runStepViews(
      makeRunGraph([
        { order: 1, label: "Sammanfatta", status: "failed" },
        { order: 2, label: "Skriv svar", status: "failed" }
      ]),
      [
        makeRunStep(1, { status: "failed", error_code: "flow_provider_rate_limited" }),
        makeRunStep(2, {
          status: "failed",
          started_at: null,
          finished_at: null,
          error_code: "flow_provider_rate_limited",
          output_payload_json: null
        })
      ]
    );
    const { container } = renderInApp(
      <RunSteps flowId="flow-1" runId="run-1" steps={steps} runStatus="failed" />
    );
    const failed = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    expect(within(failed).getByText(messages.flow_runs_step_failed_title)).toBeTruthy();
    const after = screen.getByRole("article", { name: "Steg 2: Skriv svar" });
    expect(within(after).getByText(messages.flow_run_more_step_not_run)).toBeTruthy();
    expect(within(after).queryByText(messages.flow_runs_step_status_failed)).toBeNull();
    expect(within(after).queryByText(messages.flow_runs_step_failed_title)).toBeNull();
    await expectNoAxeViolations(container);
  });
});

describe("RunSteps transcription and speakers", () => {
  it("says how a step transcribed its audio", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Transkribera", status: "completed" }]),
      [
        makeRunStep(1, {
          input_payload_json: {
            transcription: {
              files_count: 1,
              language: "sv",
              elapsed_ms: 65_000,
              model: "speech-large",
              diarization: "external",
              alignment: "segment_split"
            }
          }
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.getByText(messages.flow_run_more_transcription)).toBeTruthy();
    expect(screen.getByText(messages.flow_run_more_transcription_model)).toBeTruthy();
    expect(screen.getByText(messages.flow_run_more_transcription_language)).toBeTruthy();
    expect(screen.getByText("1 min 5 s")).toBeTruthy();
    expect(screen.getByText(messages.flow_run_more_speakers_reduced)).toBeTruthy();
  });

  it("shows whom a speaker-mapping step named, with the names given in the transcript since", async () => {
    const queryClient = testQueryClient();
    queryClient.setQueryData(runKeys.corrections("flow-1", "run-1"), [
      {
        flow_run_id: "run-1",
        step_id: "step-1",
        revision: 2,
        stale: false,
        occurrences: [],
        speaker_names: { SPEAKER_01: "Bo Ek" },
        edited_by_principal_type: "user",
        created_at: "2026-10-21T08:02:00Z",
        updated_at: "2026-10-21T08:02:00Z"
      }
    ]);
    const steps = runStepViews(makeRunGraph([{ order: 2, label: "Namnge", status: "completed" }]), [
      makeRunStep(2, {
        output_payload_json: {
          speaker_mapping: {
            source_step_id: "step-1",
            inventory: [{ label: "SPEAKER_00" }, { label: "SPEAKER_01" }]
          },
          structured: {
            speakers: [
              {
                label: "SPEAKER_00",
                name: "Anna Lind",
                confidence: "medium",
                evidence: "Hälsar som Anna."
              },
              { label: "SPEAKER_01", name: null, confidence: "low" }
            ]
          }
        }
      })
    ]);
    const { container } = renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />, {
      queryClient
    });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_step_output }));
    const speakers = screen.getByRole("list", { name: messages.flow_run_more_speakers });
    const rows = within(speakers).getAllByRole("listitem");
    expect(within(rows[0]!).getByText("Anna Lind")).toBeTruthy();
    expect(within(rows[0]!).getByText(messages.flow_run_more_confidence_medium)).toBeTruthy();
    expect(within(rows[0]!).getByText("Hälsar som Anna.")).toBeTruthy();
    expect(within(rows[1]!).getByText("Bo Ek")).toBeTruthy();
    expect(within(rows[1]!).getByText(messages.flow_run_more_confidence_high)).toBeTruthy();
    // The mapping is shown as speakers, not as its JSON.
    expect(screen.queryByText(messages.flow_run_more_json)).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("marks a structured output as JSON", () => {
    const steps = runStepViews(makeRunGraph([{ order: 1, label: "Fält", status: "completed" }]), [
      makeRunStep(1, { output_payload_json: { structured: { mottagare: "Anna" } } })
    ]);
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_step_output }));
    expect(screen.getByText(messages.flow_run_more_json)).toBeTruthy();
    expect(screen.getByText("mottagare")).toBeTruthy();
  });
});

describe("RunSteps attempts", () => {
  it("lists a step's attempts in its card when opened, for a caller who may read the evidence", async () => {
    const queryClient = testQueryClient();
    queryClient.setQueryData(runKeys.evidence("flow-1", "run-1", false), {
      step_attempts: [
        {
          id: "a-1",
          step_order: 1,
          attempt_no: 1,
          status: "failed",
          error_code: "flow_provider_rate_limited"
        },
        {
          id: "a-2",
          step_order: 1,
          attempt_no: 2,
          status: "completed",
          response_model: "model-large"
        },
        { id: "b-1", step_order: 2, attempt_no: 1, status: "completed" }
      ]
    } as unknown as RunEvidence);
    const steps = runStepViews(
      makeRunGraph([
        { order: 1, label: "Sammanfatta", status: "completed" },
        { order: 2, label: "Skriv svar", status: "completed" }
      ]),
      [makeRunStep(1), makeRunStep(2)]
    );
    const { container } = renderInApp(
      <RunSteps flowId="flow-1" runId="run-1" steps={steps} canReadEvidence />,
      { queryClient }
    );
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    expect(within(card).queryByRole("list", { name: /Försök i/ })).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_more_attempts }));
    const attempts = await within(card).findByRole("list", {
      name: messages.flow_run_more_attempts_of.replace("{step}", "Steg 1: Sammanfatta")
    });
    expect(within(attempts).getAllByRole("listitem")).toHaveLength(2);
    expect(within(attempts).getByText(/Modell model-large/)).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("does not offer the attempts to a caller who may not read the evidence", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1)]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.queryByRole("button", { name: messages.flow_run_more_attempts })).toBeNull();
  });
});
