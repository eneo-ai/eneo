// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeResultFile, makeRunGraph, makeRunStep } from "./run-fixtures";
import { RunLiveProgress } from "./run-live-progress";
import { runStepViews } from "./run-progress";
import { RunSteps } from "./run-steps";
import { runKeys } from "./runs-api";

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
        makeRunStep(1, {
          num_tokens_input: null,
          num_tokens_output: null,
          effective_prompt: "Sammanfatta."
        }),
        makeRunStep(2, {
          status: "running",
          finished_at: null,
          num_tokens_input: null,
          num_tokens_output: null,
          effective_prompt: "Skriv svar."
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

  it("counts no tokens for a step that used none, and still says when none were recorded", () => {
    const steps = runStepViews(
      makeRunGraph([
        { order: 1, label: "Transkribera", status: "completed" },
        { order: 2, label: "Sammanfatta", status: "completed" }
      ]),
      [
        makeRunStep(1, { num_tokens_input: 0, num_tokens_output: 0 }),
        makeRunStep(2, {
          num_tokens_input: null,
          num_tokens_output: null,
          effective_prompt: "Sammanfatta."
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const first = screen.getByRole("article", { name: "Steg 1: Transkribera" });
    expect(within(first).getByText("Tog 28 s")).toBeTruthy();
    expect(first.textContent).not.toMatch(/token/);
    const second = screen.getByRole("article", { name: "Steg 2: Sammanfatta" });
    expect(
      within(second).getByText(new RegExp(messages.flow_run_token_usage_not_recorded))
    ).toBeTruthy();
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
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(trigger);
  });

  it("names the earlier step instead of repeating its text in a step that made a file of it", () => {
    const notes = "## Protokoll\n\nMötet beslutade.";
    const steps = runStepViews(
      makeRunGraph([
        { order: 1, label: "Skriv protokoll", status: "completed" },
        { order: 2, label: "Skapa Word", status: "completed" }
      ]),
      [
        makeRunStep(1, { output_payload_json: { text: notes } }),
        makeRunStep(2, {
          output_payload_json: { text: notes },
          result_files: [makeResultFile({ name: "protokoll.docx" })]
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const first = screen.getByRole("article", { name: "Steg 1: Skriv protokoll" });
    expect(
      within(first).getByRole("button", { name: messages.flow_runs_step_output })
    ).toBeTruthy();
    const second = screen.getByRole("article", { name: "Steg 2: Skapa Word" });
    expect(
      within(second).getByText(messages.flow_runs_step_output_same_as.replace("{order}", "1"))
    ).toBeTruthy();
    expect(
      within(second).queryByRole("button", { name: messages.flow_runs_step_output })
    ).toBeNull();
    expect(within(second).getByText("protokoll.docx")).toBeTruthy();
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
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_step_input_show }));
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_more_copy_input }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Ärendet gäller bygglov."));
  });

  it("shows what a step was sent as it was sent, not as Markdown", () => {
    const text = "# Ärende\n\n*inte kursivt*";
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1, { input_payload_json: { text } })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_step_input_show }));
    const shown = within(card).getByLabelText(messages.flow_runs_input_heading);
    expect(shown.textContent).toBe(text);
    expect(within(shown).queryByRole("heading")).toBeNull();
  });

  it("renders what a step was sent on the first open, and keeps it for the closing", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1, { input_payload_json: { text: "Ärendet gäller bygglov." } })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    const trigger = within(card).getByRole("button", { name: messages.flow_run_step_input_show });
    expect(card.textContent).not.toContain("Ärendet gäller bygglov.");
    expect(
      within(card).queryByRole("button", { name: messages.flow_run_more_copy_input })
    ).toBeNull();

    fireEvent.click(trigger);
    expect(card.textContent).toContain("Ärendet gäller bygglov.");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(card.textContent).toContain("Ärendet gäller bygglov.");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(
      within(card).getByRole("button", { name: messages.flow_run_more_copy_input })
    ).toBeTruthy();
  });
});

describe("RunSteps warnings", () => {
  it("says a step's warning in the user's language, by its code", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [
        makeRunStep(1, {
          diagnostics: [
            {
              code: "rag_retrieval_query_truncated",
              message: "Step 1: knowledge retrieval query was truncated to 2048 characters.",
              severity: "warning"
            }
          ]
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.getByText("Sökfrågan mot kunskapen blev för lång och kortades.")).toBeTruthy();
  });

  it("says in Swedish that an uploaded file had no readable text", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [
        makeRunStep(1, {
          diagnostics: [
            {
              code: "runtime_input_source_text_unavailable",
              message: "[no readable text extracted]",
              severity: "warning"
            }
          ]
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(
      screen.getByText(messages.flow_step_warning_runtime_input_source_text_unavailable)
    ).toBeTruthy();
    expect(screen.queryByText("[no readable text extracted]")).toBeNull();
  });

  it("says nothing of tokens for a step that used no model, such as an HTTP call", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Hämta ärendet", status: "completed" }]),
      [makeRunStep(1, { num_tokens_input: null, num_tokens_output: null })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Hämta ärendet" });
    expect(card.textContent).not.toMatch(/[Tt]oken/);
  });
});

describe("RunSteps input and output", () => {
  const transcript = "[00:00:00 - 00:00:07] SPEAKER_00: Välkomna till mötet.";

  it("shows what a step was sent as JSON, without what its card already shows", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const input = {
      text: transcript,
      transcription: { file_ids: ["audio-1"], language: "sv" },
      rag: { status: "skipped_transcribe_only", sources: [] },
      input_source: "flow_input"
    };
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Transkribera", status: "completed" }]),
      [makeRunStep(1, { input_payload_json: input, output_payload_json: { text: transcript } })]
    );
    const { container } = renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Transkribera" });
    expect(card.className).toContain("min-w-0");
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_step_input_show }));
    const json = card.querySelector("[data-json-block]")!.textContent;
    expect(json).toContain('"input_source": "flow_input"');
    for (const shown of ["transcription", "rag", "SPEAKER_00"]) expect(json).not.toContain(shown);
    await expectNoAxeViolations(container);
    // A copy is all of it, for support.
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_more_copy_input }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(JSON.stringify(input, null, 2)));
  });

  /** The core's payload for a step sent a text: the text twice, and how it got there. */
  const textInput = (text: string, more: Record<string, unknown> = {}) => ({
    text,
    text_truncated: false,
    source_text: text,
    source_text_truncated: false,
    material_aliases: [],
    input_source: "flow_input",
    used_question_binding: false,
    effective_prompt_truncated: false,
    ...more
  });

  function openInput(input: Record<string, unknown>) {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1, { input_payload_json: input })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    fireEvent.click(within(card).getByRole("button", { name: messages.flow_run_step_input_show }));
    return card;
  }

  it("shows a step sent only a text as that text, once, not as JSON", () => {
    const card = openInput(textInput("Ärendet gäller bygglov."));
    expect(card.querySelector("[data-json-block]")).toBeNull();
    const [text, ...repeats] = within(card).getAllByText("Ärendet gäller bygglov.");
    expect(text?.closest(".astryx-scrollable-area")).not.toBeNull();
    expect(repeats).toEqual([]);
  });

  it("keeps the JSON when the input says more than its text", () => {
    for (const input of [
      textInput("Ärendet.", { source_text: "Originalet." }),
      textInput("Ärendet.", { text_truncated: true }),
      textInput("Ärendet.", { material_aliases: [{ alias: "step_1" }] }),
      textInput("Ärendet.", { other: "något" })
    ]) {
      const card = openInput(input);
      expect(card.querySelector("[data-json-block]")).not.toBeNull();
      cleanup();
    }
  });

  it("offers no input when the card already shows all of it", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Transkribera", status: "completed" }]),
      [makeRunStep(1, { input_payload_json: { transcription: {}, rag: {} } })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.queryByRole("button", { name: messages.flow_run_step_input_show })).toBeNull();
  });

  it("keeps a step's text in a box that wraps and scrolls past its height", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1)]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_step_output }));
    const box = screen.getByText("Resultat från steg 1").closest(".astryx-scrollable-area");
    expect(box?.className).toContain("max-h-96");
    expect(box?.className).toContain("[overflow-wrap:anywhere]");
  });

  it("shows a transcribing step's transcript as its result, open, and any other step's beside it", () => {
    const host = (text: string) =>
      Object.assign(document.createElement("div"), { textContent: text });
    const transcripts = new Map([
      ["step-1", host("Transkriptet från steg 1")],
      ["step-2", host("Transkriptet från steg 2")]
    ]);
    const [first, second] = runStepViews(
      makeRunGraph([
        { order: 1, label: "Transkribera", status: "completed" },
        { order: 2, label: "Sammanfatta mötet", status: "completed" }
      ]),
      [
        makeRunStep(1, { output_payload_json: { text: transcript } }),
        makeRunStep(2, { output_payload_json: { text: "Mötet beslutade." } })
      ]
    );
    renderInApp(
      <RunSteps
        flowId="flow-1"
        runId="run-1"
        steps={[{ ...first!, transcribeOnly: true }, second!]}
        transcripts={transcripts}
      />
    );
    const one = screen.getByRole("article", { name: "Steg 1: Transkribera" });
    const result = within(one).getByRole("button", { name: messages.flow_runs_transcript_heading });
    expect(result.getAttribute("aria-expanded")).toBe("true");
    expect(within(one).getByText("Transkriptet från steg 1")).toBeTruthy();
    // The transcript, not its raw lines.
    expect(one.textContent).not.toContain("SPEAKER_00");

    const two = screen.getByRole("article", { name: "Steg 2: Sammanfatta mötet" });
    const section = within(two).getByRole("button", {
      name: messages.flow_runs_transcript_heading
    });
    expect(section.getAttribute("aria-expanded")).toBe("true");
    expect(within(two).getByText("Transkriptet från steg 2")).toBeTruthy();
    // Folding it keeps the transcript's element, to show it again as it was.
    fireEvent.click(section);
    expect(section.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(section);
    expect(within(two).getByText("Transkriptet från steg 2")).toBe(transcripts.get("step-2"));
  });

  it("stops a transcript's sound when its panel closes", () => {
    const [first, second] = runStepViews(
      makeRunGraph([
        { order: 1, label: "Transkribera", status: "completed" },
        { order: 2, label: "Sammanfatta mötet", status: "completed" }
      ]),
      [
        makeRunStep(1, { output_payload_json: { text: transcript } }),
        makeRunStep(2, { output_payload_json: { text: "Mötet beslutade." } })
      ]
    );
    const host = document.createElement("div");
    const audio = host.appendChild(document.createElement("audio"));
    const pause = vi.spyOn(audio, "pause").mockImplementation(() => undefined);
    renderInApp(
      <RunSteps
        flowId="flow-1"
        runId="run-1"
        steps={[first!, second!]}
        transcripts={new Map([["step-2", host]])}
      />
    );
    expect(pause).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_transcript_heading }));
    expect(pause).toHaveBeenCalledTimes(1);
  });

  /** A finished transcribing step, and the element its transcript renders into. */
  function transcribed() {
    const [step] = runStepViews(
      makeRunGraph([{ order: 1, label: "Transkribera", status: "completed" }]),
      [makeRunStep(1, { output_payload_json: { text: transcript } })]
    );
    const host = Object.assign(document.createElement("div"), { textContent: "Transkriptet" });
    return {
      steps: [{ ...step!, transcribeOnly: true }],
      transcripts: new Map([["step-1", host]])
    };
  }

  it("leaves the copy of a transcribing step to the transcript, whose export has the corrections", () => {
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" {...transcribed()} />);
    const card = screen.getByRole("article", { name: "Steg 1: Transkribera" });
    expect(
      within(card).queryByRole("button", { name: messages.flow_run_more_copy_output })
    ).toBeNull();
  });

  it("opens a step's result for a transcript that arrives after its card", () => {
    const { steps, transcripts } = transcribed();
    const { rerender } = renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const result = () => screen.getByRole("button", { name: /Stegets resultat|Transkription/ });
    expect(result().getAttribute("aria-expanded")).toBe("false");

    rerender(<RunSteps flowId="flow-1" runId="run-1" steps={steps} transcripts={transcripts} />);
    expect(result().getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Transkriptet")).toBeTruthy();
  });

  it("keeps a result the person folded folded when its transcript arrives", () => {
    const { steps, transcripts } = transcribed();
    const { rerender } = renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const result = () => screen.getByRole("button", { name: /Stegets resultat|Transkription/ });
    fireEvent.click(result());
    fireEvent.click(result());

    rerender(<RunSteps flowId="flow-1" runId="run-1" steps={steps} transcripts={transcripts} />);
    expect(result().getAttribute("aria-expanded")).toBe("false");
  });

  it("folds the transcript of a run that has ended, and keeps it open while the run awaits review", () => {
    const { steps, transcripts } = transcribed();
    const speaking = [{ ...steps[0]!, speakerIdentification: true }];
    const name = messages.flow_runs_transcript_and_speakers;
    renderInApp(
      <RunSteps
        flowId="flow-1"
        runId="run-1"
        steps={speaking}
        runStatus="completed"
        transcripts={transcripts}
      />
    );
    expect(screen.getByRole("button", { name }).getAttribute("aria-expanded")).toBe("false");
    cleanup();

    renderInApp(
      <RunSteps
        flowId="flow-1"
        runId="run-1"
        steps={speaking}
        runStatus="awaiting_review"
        transcripts={transcripts}
      />
    );
    expect(screen.getByRole("button", { name }).getAttribute("aria-expanded")).toBe("true");
  });

  it("keeps a transcript open when the run ends while it is read", () => {
    const { steps, transcripts } = transcribed();
    const { rerender } = renderInApp(
      <RunSteps
        flowId="flow-1"
        runId="run-1"
        steps={steps}
        runStatus="running"
        transcripts={transcripts}
      />
    );
    const result = () =>
      screen.getByRole("button", { name: messages.flow_runs_transcript_heading });
    expect(result().getAttribute("aria-expanded")).toBe("true");
    rerender(
      <RunSteps
        flowId="flow-1"
        runId="run-1"
        steps={steps}
        runStatus="completed"
        transcripts={transcripts}
      />
    );
    expect(result().getAttribute("aria-expanded")).toBe("true");
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
  function openSettings(parameters: Record<string, unknown>) {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1, { model_parameters_json: parameters })]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    const card = screen.getByRole("article", { name: "Steg 1: Sammanfatta" });
    const trigger = within(card).queryByRole("button", {
      name: messages.flow_run_extras_prompt_heading
    });
    if (trigger) fireEvent.click(trigger);
    return card;
  }

  it("names a step's model settings in words and leaves out what is empty or the core's own", () => {
    const card = openSettings({
      model_id: "11111111-2222-3333-4444-555555555555",
      model_name: "GPT-5",
      provider: "openai",
      temperature: 0,
      top_p: null,
      top_k: 40,
      reasoning_effort: null,
      verbosity: "",
      response_format: null,
      presence_penalty: null,
      frequency_penalty: null,
      parameter_semantics: { temperature: { mode: "configured" } },
      per_source_call_count: 3,
      a_setting_of_tomorrow: "på"
    });

    expect(within(card).getByText(messages.model)).toBeTruthy();
    expect(within(card).getByText("GPT-5")).toBeTruthy();
    expect(within(card).getByText(messages.provider)).toBeTruthy();
    // A value of 0 is a setting, not an empty one.
    expect(within(card).getByText(messages.temperature)).toBeTruthy();
    expect(within(card).getByText("0")).toBeTruthy();
    expect(within(card).getByText(messages.top_k)).toBeTruthy();
    expect(within(card).getByText(messages.flow_run_setting_per_source_calls)).toBeTruthy();
    // A setting the catalog does not know yet still shows.
    expect(within(card).getByText("a_setting_of_tomorrow")).toBeTruthy();

    expect(within(card).queryByText(messages.flow_runs_value_empty)).toBeNull();
    for (const hidden of [messages.top_p, messages.verbosity, "parameter_semantics"]) {
      expect(within(card).queryByText(hidden)).toBeNull();
    }
    expect(card.textContent).not.toContain("11111111-2222");
  });

  it("offers no model settings for a step whose parameters are only the core's bookkeeping", () => {
    const card = openSettings({ mode: "transcribe_only" });
    expect(
      within(card).queryByRole("button", { name: messages.flow_run_extras_prompt_heading })
    ).toBeNull();
  });

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
            template_provenance: {
              template_name: "Beslutsmall",
              published_flow_version: 4,
              template_asset_id: "asset-9",
              template_checksum: "sha-9"
            }
          }
        })
      ]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.getByText("Läst del för del: 2 delar.")).toBeTruthy();
    expect(screen.getByText(/del 1: 0–40 %, del 2: 40–100 %/)).toBeTruthy();
    expect(screen.getByText(messages.flow_run_template_provenance_label)).toBeTruthy();
    expect(screen.getByText("Beslutsmall")).toBeTruthy();
    // The run header carries the flow's version; the template's ids are for the API, not the reader.
    expect(screen.queryByText(/v4|asset-9|sha-9/)).toBeNull();
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
    for (const fact of ["1 fil", /^Utläst text: 1\s234 tecken$/, "Format: Dokument"]) {
      expect(screen.getByText(fact)).toBeTruthy();
    }
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
  it("leaves a step's attempts to the evidence, even for a caller who may read it", () => {
    const steps = runStepViews(
      makeRunGraph([{ order: 1, label: "Sammanfatta", status: "completed" }]),
      [makeRunStep(1)]
    );
    renderInApp(<RunSteps flowId="flow-1" runId="run-1" steps={steps} />);
    expect(screen.queryByRole("button", { name: "Försök" })).toBeNull();
  });
});
