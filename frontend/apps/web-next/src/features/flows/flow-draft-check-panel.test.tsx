// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeAssistant } from "./editor/testing/fixtures";
import { makeFlow, makeStep } from "./flow-fixtures";

const state = vi.hoisted(() => ({ announce: vi.fn() }));
const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
  PUT: vi.fn(),
  DELETE: vi.fn()
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

import { templateInspectionQueryOptions } from "./editor/editor-api";
import { FlowDraftCheck } from "./flow-draft-check-panel";
import { SUGGESTIONS_SUMMARY_ID } from "./flow-suggestions-section";
import { flowSuggestionsQueryOptions } from "./flow-suggestions";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const reply = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

/** The assistants by id, and the draft's suggestions (dismissed ones marked, as the page reads them). */
function route(assistants: Record<string, unknown>, suggestions: Record<string, unknown>[] = []) {
  api.GET.mockImplementation((path: string, init: { params: { path: { assistant_id: string } } }) =>
    Promise.resolve(
      path === "/api/v1/flows/{id}/suggestions/"
        ? reply({
            flow_id: "flow-1",
            draft_revision: 4,
            dismissed_count: suggestions.filter((item) => item.dismissed).length,
            items: suggestions
          })
        : reply(assistants[init.params.path.assistant_id])
    )
  );
  api.POST.mockResolvedValue(reply({ steps: [] }));
}

function suggestion(fingerprint: string, steps: string[], dismissed = false) {
  return {
    code: steps.length > 0 ? "unread_result" : "unused_form_field",
    fingerprint: fingerprint.repeat(64),
    steps,
    params: steps.length > 0 ? {} : { field: "Diarienummer" },
    message: "A suggestion.",
    impact: { basis: "definition", level: "medium" },
    fix: { kind: "advice" },
    dismissed: dismissed ? { dismissed_by: "user-1", dismissed_at: "2026-10-25T09:30:00Z" } : null
  };
}

const ASSISTANTS = {
  "assistant-1": makeAssistant({ id: "assistant-1" }),
  "assistant-2": makeAssistant({ id: "assistant-2" })
};

describe("FlowDraftCheck", () => {
  it("lists what stops publishing per step and opens the step it is about", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({ id: "assistant-2", completion_model: null })
    });
    const onOpenStep = vi.fn();
    const flow = makeFlow();
    const { container } = renderInApp(
      <FlowDraftCheck
        flow={flow}
        transcription={{ models: [], services: [] }}
        onOpenStep={onOpenStep}
      />
    );

    expect(await screen.findByText("1 sak hindrar publicering")).toBeTruthy();
    expect(screen.getByText("Välj en AI-modell för steget.")).toBeTruthy();
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Öppna Steg 2: Skriv svar" }));
    // At the field that fixes it, not the step's top.
    expect(onOpenStep).toHaveBeenCalledWith(flow.steps[1], "completion_model");
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/flows/{id}/security-classification/preview",
      expect.objectContaining({ params: { path: { id: "flow-1" } } })
    );
  });

  it("replaces a read of a removed step with an earlier answer in one choice", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({ id: "assistant-2" })
    });
    const flow = makeFlow({
      steps: [
        makeStep(1, { user_description: "Sammanfatta" }),
        makeStep(2, {
          user_description: "Skriv svar",
          input_bindings: { question: "Svara på {{step_3_deleted.output.text}}" }
        })
      ]
    });
    const onRepair = vi.fn().mockResolvedValue(true);
    const { container } = renderInApp(
      <FlowDraftCheck
        flow={flow}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
        onRepair={onRepair}
      />
    );

    expect(
      await screen.findByText("{{step_3_deleted.output.text}} i underlaget går inte att läsa.")
    ).toBeTruthy();
    await expectNoAxeViolations(container);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Välj vad som ska användas i stället för {{step_3_deleted.output.text}} i Steg 2: Skriv svar"
      })
    );
    fireEvent.click(await screen.findByRole("menuitem", { name: /Steg 1: Sammanfatta/ }));
    expect(onRepair).toHaveBeenCalledWith(flow.steps[1], {
      question: "Svara på {{step_1.output.text}}"
    });
  });

  it("names the references a step cannot read, and what each one reads wrong", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({
        id: "assistant-2",
        prompt: {
          text: "Skriv {{datun}} och {{step_1.output.structured.namn}} och {{step_3.output.text}}.",
          description: null
        }
      } as never)
    });
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow()}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
      />
    );

    expect(
      await screen.findByText(
        "{{datun}}, {{step_1.output.structured.namn}} och {{step_3.output.text}} i instruktionen går inte att läsa. " +
          "Steg 1: Sammanfatta svarar inte i fast format och har inga fält att läsa. " +
          "Läs svaret som text, eller låt steget svara i fast format."
      )
    ).toBeTruthy();
  });

  it("names the Word fields nothing fills as the template titles them", async () => {
    route(ASSISTANTS);
    const queryClient = testQueryClient();
    queryClient.setQueryData(templateInspectionQueryOptions("flow-1", "t-1").queryKey, {
      file_id: "f-1",
      file_name: "Beslut.docx",
      placeholders: [
        { name: "arende", label: "Ärende", kind: "text", location: "body" },
        { name: "datum_tag", label: "", kind: "text", location: "body" }
      ]
    });
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow({
          steps: [
            makeStep(1, {
              user_description: "Fyll mallen",
              output_mode: "template_fill",
              output_type: "docx",
              output_config: {
                template_asset_id: "t-1",
                placeholders: ["arende", "datum_tag"],
                bindings: {}
              }
            })
          ]
        })}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
      />,
      { queryClient }
    );

    // A field without a title is named by its tag, as the editor does.
    expect(
      await screen.findByText(
        "Välj vad som ska stå i fälten ”Ärende” och ”datum_tag” i Word-mallen."
      )
    ).toBeTruthy();
  });

  it("does not say the draft is ready while the page shows publishing was refused", async () => {
    route(ASSISTANTS);
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow()}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
        refused
      />
    );

    expect(await screen.findByText("Publiceringen nekades. Se meddelandet ovan.")).toBeTruthy();
    expect(screen.queryByText("Redo att publicera")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Kontrollera igen" }));
    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith("Publiceringen nekades. Se meddelandet ovan.")
    );
    expect(state.announce).not.toHaveBeenCalledWith("Redo att publicera");
  });

  it("fixes the flow's own problems where they are fixed: in its settings", async () => {
    route(ASSISTANTS);
    const onOpenSettings = vi.fn();
    const onProblemCount = vi.fn();
    const audio = makeFlow({
      steps: [
        makeStep(1, { input_type: "audio", output_mode: "transcribe_only" }),
        makeStep(2, {
          output_mode: "speaker_mapping",
          output_type: "json",
          output_config: { speaker_mapping: { infer_names: true } }
        })
      ],
      metadata_json: { wizard: { transcription_enabled: true } }
    });
    const { container } = renderInApp(
      <FlowDraftCheck
        flow={audio}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
        onOpenSettings={onOpenSettings}
        onProblemCount={onProblemCount}
      />
    );

    const model = await screen.findByText("Välj en transkriberingsmodell i flödets inställningar.");
    const [first, second] = screen.getAllByRole("button", { name: "Öppna inställningar" });
    // Each button is described by the problem beside it.
    expect(first!.getAttribute("aria-describedby")).toBe(model.id);
    await expectNoAxeViolations(container);
    fireEvent.click(first!);
    expect(onOpenSettings).toHaveBeenLastCalledWith("transcription_model");
    fireEvent.click(second!);
    expect(onOpenSettings).toHaveBeenLastCalledWith("speaker_service");
    // The page is told the count once the check has an answer.
    expect(onProblemCount).toHaveBeenLastCalledWith(2);
  });

  it("holds the clean result's one line while it checks, so what follows stays put", async () => {
    route(ASSISTANTS);
    let answer!: (value: unknown) => void;
    api.POST.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow()}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
      />
    );

    const running = await screen.findByText("Kontrollerar utkastet…");
    answer(reply({ steps: [] }));
    const clean = await screen.findByText("Redo att publicera");
    // The same line, its text swapped, and no banner around it.
    expect(clean.parentElement).toBe(running.parentElement);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/kontrollerar flödet en gång till/)).toBeNull();
  });

  it("says the draft is ready to publish, and announces it when checked again", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({ id: "assistant-2" })
    });
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow({ steps: [makeStep(1, { user_description: "Sammanfatta" })] })}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
      />
    );
    expect(await screen.findByText("Redo att publicera")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Kontrollera igen" }));
    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("Redo att publicera"));
  });

  it("says how many suggestions the draft has, and brings their summary into view and focus", async () => {
    route(ASSISTANTS, [
      suggestion("a", ["step-2"]),
      suggestion("b", []),
      // Dismissed: shown under "Visa ignorerade", never counted.
      suggestion("c", ["step-1"], true),
      // About a step the draft no longer has: shown nowhere.
      suggestion("d", ["step-9"])
    ]);
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView");
    const { container } = renderInApp(
      <>
        <FlowDraftCheck
          flow={makeFlow()}
          transcription={{ models: [], services: [] }}
          onOpenStep={vi.fn()}
        />
        {/* The step list's summary, as the page puts it below. */}
        <div id={SUGGESTIONS_SUMMARY_ID} tabIndex={-1}>
          Sammanfattningen
        </div>
      </>
    );

    expect(
      await screen.findByText("2 förslag kan göra flödet enklare eller billigare")
    ).toBeTruthy();
    // Advice beside the check: what stops publishing is still nothing.
    expect(screen.getByText("Redo att publicera")).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Visa förslagen" }));
    const summary = document.getElementById(SUGGESTIONS_SUMMARY_ID)!;
    expect(document.activeElement).toBe(summary);
    expect(scrolled.mock.contexts).toContain(summary);
    scrolled.mockRestore();
  });

  it("says nothing of suggestions while the draft has none, or only dismissed ones", async () => {
    route(ASSISTANTS, [suggestion("c", ["step-1"], true)]);
    const queryClient = testQueryClient();
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow()}
        transcription={{ models: [], services: [] }}
        onOpenStep={vi.fn()}
      />,
      {
        queryClient
      }
    );

    expect(await screen.findByText("Redo att publicera")).toBeTruthy();
    await waitFor(() =>
      expect(
        queryClient.getQueryData(flowSuggestionsQueryOptions("flow-1", 4).queryKey)
      ).toBeTruthy()
    );
    expect(screen.queryByText(/förslag kan göra flödet/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Visa förslagen" })).toBeNull();
  });
});
