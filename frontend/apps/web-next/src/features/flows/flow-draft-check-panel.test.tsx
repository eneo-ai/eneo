// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
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

import { FlowDraftCheck } from "./flow-draft-check-panel";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const reply = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

function route(assistants: Record<string, unknown>) {
  api.GET.mockImplementation(
    (_path: string, init: { params: { path: { assistant_id: string } } }) =>
      Promise.resolve(reply(assistants[init.params.path.assistant_id]))
  );
  api.POST.mockResolvedValue(reply({ steps: [] }));
}

describe("FlowDraftCheck", () => {
  it("lists what stops publishing per step and opens the step it is about", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({ id: "assistant-2", completion_model: null })
    });
    const onOpenStep = vi.fn();
    const flow = makeFlow();
    const { container } = renderInApp(
      <FlowDraftCheck flow={flow} speakerServices={[]} onOpenStep={onOpenStep} />
    );

    expect(await screen.findByText("1 sak hindrar publicering")).toBeTruthy();
    expect(screen.getByText("Välj en AI-modell för steget.")).toBeTruthy();
    await expectNoAxeViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Öppna Steg 2: Skriv svar" }));
    expect(onOpenStep).toHaveBeenCalledWith(flow.steps[1]);
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
      <FlowDraftCheck flow={flow} speakerServices={[]} onOpenStep={vi.fn()} onRepair={onRepair} />
    );

    expect(
      await screen.findByText(
        "Hänvisningen {{step_3_deleted.output.text}} gäller ett steg som inte finns längre."
      )
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

  it("says nothing stops publishing, and announces it when checked again", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({ id: "assistant-2" })
    });
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow({ steps: [makeStep(1, { user_description: "Sammanfatta" })] })}
        speakerServices={[]}
        onOpenStep={vi.fn()}
      />
    );
    expect(await screen.findByText("Inget hindrar publicering just nu.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Kontrollera igen" }));
    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith("Inget hindrar publicering just nu.")
    );
  });

  it("lists no suggestions: they sit on the step cards", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({ id: "assistant-2" })
    });
    renderInApp(<FlowDraftCheck flow={makeFlow()} speakerServices={[]} onOpenStep={vi.fn()} />);

    expect(await screen.findByText("Inget hindrar publicering just nu.")).toBeTruthy();
    expect(api.GET).not.toHaveBeenCalledWith("/api/v1/flows/{id}/suggestions/", expect.anything());
  });
});
