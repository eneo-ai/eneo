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

/** One `duplicate_read` on step 2, reading step 1 as its input and in its prompt. */
const DUPLICATE_READ = {
  code: "duplicate_read",
  fingerprint: "f".repeat(64),
  steps: ["step-2", "step-1"],
  params: {
    producer_step_order: 1,
    producer_step_id: "step-1",
    contained: false,
    reads: [
      { channel: "input", site: "input_source", selector: [] },
      { channel: "prompt", site: "assistant_prompt:step_1.output.text", selector: [] }
    ]
  },
  message: "Step 2 reads step 1 twice.",
  impact: { basis: "definition", level: "high" },
  fix: { kind: "patch" }
};

function route(assistants: Record<string, unknown>, suggestions: unknown[] = []) {
  api.GET.mockImplementation((path: string, init: { params: { path: { assistant_id: string } } }) =>
    Promise.resolve(
      path === "/api/v1/flows/{id}/suggestions/"
        ? reply({ flow_id: "flow-1", draft_revision: 4, items: suggestions })
        : reply(assistants[init.params.path.assistant_id])
    )
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

  it("shows the core's suggestions apart from the blockers and opens their step", async () => {
    route(
      {
        "assistant-1": makeAssistant({ id: "assistant-1" }),
        "assistant-2": makeAssistant({ id: "assistant-2" })
      },
      [DUPLICATE_READ]
    );
    const onOpenStep = vi.fn();
    const flow = makeFlow();
    const { container } = renderInApp(
      <FlowDraftCheck
        flow={flow}
        speakerServices={[]}
        onOpenStep={onOpenStep}
        onAskChat={vi.fn()}
      />
    );

    expect(await screen.findByRole("heading", { level: 3, name: "Förslag (1)" })).toBeTruthy();
    expect(screen.getByText("Inget hindrar publicering just nu.")).toBeTruthy();
    expect(screen.getByText("Svaret från steg 1 skickas två gånger")).toBeTruthy();
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/flows/{id}/suggestions/",
      expect.objectContaining({ params: { path: { id: "flow-1" } } })
    );

    // A native disclosure: a button that says whether the region it controls is open.
    const why = screen.getByRole("button", {
      name: "Varför? Svaret från steg 1 skickas två gånger"
    });
    expect(why.tagName).toBe("BUTTON");
    expect(why.getAttribute("aria-expanded")).toBe("false");
    const region = document.getElementById(why.getAttribute("aria-controls") ?? "")!;
    expect(region.hidden).toBe(true);
    await expectNoAxeViolations(container);
    fireEvent.click(why);
    expect(why.getAttribute("aria-expanded")).toBe("true");
    expect(region.hidden).toBe(false);
    expect(region.textContent).toMatch(
      /Steget får samma text som indata \(föregående steg\) och i prompten/
    );
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: "Öppna Steg 2: Skriv svar" }));
    expect(onOpenStep).toHaveBeenCalledWith(flow.steps[1]);
  });

  it("hands a prepared request about a suggestion to the flow chat", async () => {
    route(
      {
        "assistant-1": makeAssistant({ id: "assistant-1" }),
        "assistant-2": makeAssistant({ id: "assistant-2" })
      },
      [DUPLICATE_READ]
    );
    const onAskChat = vi.fn();
    const { container } = renderInApp(
      <FlowDraftCheck
        flow={makeFlow()}
        speakerServices={[]}
        onOpenStep={vi.fn()}
        onAskChat={onAskChat}
      />
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Fråga assistenten om ”Svaret från steg 1 skickas två gånger” (Steg 2: Skriv svar)"
      })
    );
    expect(onAskChat).toHaveBeenCalledWith(
      "Förklara förslaget ”Svaret från steg 1 skickas två gånger” (duplicate_read) som gäller " +
        "steg 2 (Skriv svar) och steg 1 (Sammanfatta), och föreslå hur flödet kan ändras."
    );
    await expectNoAxeViolations(container);
  });

  it("shows a kind of suggestion it does not know with the generic text, still to ask about", async () => {
    route(
      {
        "assistant-1": makeAssistant({ id: "assistant-1" }),
        "assistant-2": makeAssistant({ id: "assistant-2" })
      },
      [{ ...DUPLICATE_READ, code: "some_later_code", params: {}, fix: { kind: "advice" } }]
    );
    const onAskChat = vi.fn();
    renderInApp(
      <FlowDraftCheck
        flow={makeFlow()}
        speakerServices={[]}
        onOpenStep={vi.fn()}
        onAskChat={onAskChat}
      />
    );

    expect(await screen.findByText("Förslag", { selector: "p" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Fråga assistenten/ }));
    expect(onAskChat).toHaveBeenCalledWith(expect.stringContaining("(some_later_code)"));
  });

  it("offers no request to the chat while the chat is not available", async () => {
    route(
      {
        "assistant-1": makeAssistant({ id: "assistant-1" }),
        "assistant-2": makeAssistant({ id: "assistant-2" })
      },
      [DUPLICATE_READ]
    );
    renderInApp(<FlowDraftCheck flow={makeFlow()} speakerServices={[]} onOpenStep={vi.fn()} />);

    expect(await screen.findByText("Svaret från steg 1 skickas två gånger")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Fråga assistenten/ })).toBeNull();
  });

  it("renders no suggestions section while the draft gives none", async () => {
    route({
      "assistant-1": makeAssistant({ id: "assistant-1" }),
      "assistant-2": makeAssistant({ id: "assistant-2" })
    });
    renderInApp(<FlowDraftCheck flow={makeFlow()} speakerServices={[]} onOpenStep={vi.fn()} />);

    expect(await screen.findByText("Inget hindrar publicering just nu.")).toBeTruthy();
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/flows/{id}/suggestions/", expect.anything())
    );
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
    expect(screen.queryByText(/Förslag/)).toBeNull();
  });
});
