// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeStep } from "./flow-fixtures";

const prompts = vi.hoisted(() => ({
  byAssistant: {} as Record<string, string>,
  suggestions: [] as unknown[]
}));
const api = vi.hoisted(() => ({
  GET: vi.fn(async (path: string, init: { params: { path: { assistant_id: string } } }) => {
    if (path === "/api/v1/flows/{id}/suggestions/") {
      return {
        data: { flow_id: "flow-1", draft_revision: 4, items: prompts.suggestions },
        response: new Response(null, { status: 200 })
      };
    }
    const id = init.params.path.assistant_id;
    return {
      data: { id, prompt: { text: prompts.byAssistant[id] ?? "" } },
      response: new Response(null, { status: 200 })
    };
  })
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { FlowStepList, type SpeakerStepOffer } from "./flow-step-list";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  prompts.byAssistant = {};
  prompts.suggestions = [];
});

/** A suggestion about `stepId` (its first step), reading step 1. */
function suggestionAbout(stepId: string, fingerprint: string) {
  return {
    code: "duplicate_read",
    fingerprint,
    steps: [stepId, "step-1"],
    params: { producer_step_order: 1, producer_step_id: "step-1", reads: [] },
    message: "Reads step 1 twice.",
    impact: { basis: "definition", level: "high" },
    fix: { kind: "assisted" }
  };
}

const steps = [
  makeStep(1, { user_description: "Sammanfatta", input_type: "document" }),
  makeStep(2, {
    user_description: "Skriv svar",
    output_type: "docx",
    output_mode: "render_verbatim",
    review_policy: { mode: "edit" }
  }),
  makeStep(3, { user_description: "Granska", input_bindings: { question: "{{step_1}}" } })
];

function renderList(canEdit = true, speakerOffer: SpeakerStepOffer | null = null) {
  const actions = {
    onOpen: vi.fn(),
    onMove: vi.fn(),
    onRemove: vi.fn(async () => {}),
    onAdd: vi.fn()
  };
  const view = renderInApp(
    <FlowStepList
      flowId="flow-1"
      draftRevision={4}
      steps={steps}
      canEdit={canEdit}
      headingRef={createRef()}
      speakerOffer={speakerOffer}
      {...actions}
    />
  );
  return { ...view, actions };
}

describe("FlowStepList", () => {
  it("offers the step that names the speakers in the card of the step it follows", async () => {
    const onAccept = vi.fn();
    const { container } = renderList(true, { stepId: "step-1", pending: false, onAccept });
    const card = screen.getByRole("article", { name: /Sammanfatta/ });
    expect(within(card).getByText("Vill du granska transkriptet?")).toBeTruthy();
    await expectNoAxeViolations(container);
    fireEvent.click(
      within(card).getByRole("button", {
        name: "Lägg till ett steg som granskar transkriptet efter Steg 1: Sammanfatta"
      })
    );
    expect(onAccept).toHaveBeenCalledTimes(1);
  });

  it("lists the steps in order with what each reads, takes and produces", async () => {
    const { container } = renderList();
    const list = screen.getByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);

    const second = within(items[1]!).getByRole("article", { name: "Steg 2 Skriv svar" });
    expect(within(second).getByText("Steg 1: Sammanfatta")).toBeTruthy();
    expect(within(second).getByText("Word-dokument, dokument utan AI")).toBeTruthy();
    expect(within(second).getByText("Pausar för granskning och ändring")).toBeTruthy();
    expect(within(items[0]!).getByText("Det som skickas in")).toBeTruthy();
    expect(within(items[0]!).getByText("Dokument")).toBeTruthy();
    // The third step reads the first by its binding, not the step before it.
    expect(within(items[2]!).getByText("Steg 1: Sammanfatta")).toBeTruthy();

    await expectNoAxeViolations(container);
  });

  it("adds what an AI step's prompt reads, and names a prompt reader before a removal", async () => {
    prompts.byAssistant = {
      "assistant-3": "Jämför med {{step_2.output.text}} och {{Sammanfatta}}."
    };
    renderList();
    const third = screen.getByRole("article", { name: "Steg 3 Granska" });
    expect(await within(third).findByText("Steg 2: Skriv svar")).toBeTruthy();
    expect(within(third).getByText("Steg 1: Sammanfatta")).toBeTruthy();

    const trigger = screen.getByRole("button", { name: "Fler åtgärder för Steg 2: Skriv svar" });
    fireEvent.click(trigger);
    const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort steg" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort steget?" });
    expect(within(dialog).getByText(/^Steg 3: Granska läser Steg 2: Skriv svar\./)).toBeTruthy();
  });

  it("moves a step with buttons, never past either end", () => {
    const { actions } = renderList();
    const up = screen.getByRole("button", { name: "Flytta upp Steg 1: Sammanfatta" });
    expect((up as HTMLButtonElement).disabled).toBe(true);
    const down = screen.getByRole("button", { name: "Flytta ner Steg 3: Granska" });
    expect((down as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Flytta ner Steg 1: Sammanfatta" }));
    expect(actions.onMove).toHaveBeenCalledWith(steps[0], 1);
    fireEvent.click(screen.getByRole("button", { name: "Redigera Steg 2: Skriv svar" }));
    expect(actions.onOpen).toHaveBeenCalledWith(steps[1]);
    fireEvent.click(screen.getByRole("button", { name: "Lägg till steg" }));
    expect(actions.onAdd).toHaveBeenCalledWith(4);
  });

  it("names the steps that read a step before it is removed", async () => {
    const { actions } = renderList();
    const trigger = screen.getByRole("button", { name: "Fler åtgärder för Steg 1: Sammanfatta" });
    fireEvent.click(trigger);
    const menu = document.getElementById(trigger.getAttribute("aria-controls") ?? "")!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Ta bort steg" }));

    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort steget?" });
    expect(
      within(dialog).getByText(
        "Steg 3: Granska läser Steg 1: Sammanfatta. Ändra först vad de läser, annars nekas borttagningen."
      )
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort steg" }));
    await waitFor(() => expect(actions.onRemove).toHaveBeenCalledWith(steps[0]));
  });

  it("marks each step the core has suggestions about with their count", async () => {
    prompts.suggestions = [
      suggestionAbout("step-2", "a".repeat(64)),
      suggestionAbout("step-2", "b".repeat(64)),
      suggestionAbout("step-3", "c".repeat(64)),
      // A step the draft no longer has gets no marker anywhere.
      suggestionAbout("step-9", "d".repeat(64))
    ];
    const { container } = renderList();

    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    expect(await within(second).findByText("2 förslag för Steg 2: Skriv svar")).toBeTruthy();
    const third = screen.getByRole("article", { name: "Steg 3 Granska" });
    expect(within(third).getByText("1 förslag för Steg 3: Granska")).toBeTruthy();
    expect(within(third).getByText("1 förslag").getAttribute("aria-hidden")).toBe("true");
    const first = screen.getByRole("article", { name: "Steg 1 Sammanfatta" });
    expect(within(first).queryByText(/förslag/)).toBeNull();
    // One request, keyed like the draft check's.
    expect(
      api.GET.mock.calls.filter(([path]) => path === "/api/v1/flows/{id}/suggestions/")
    ).toHaveLength(1);
    await expectNoAxeViolations(container);
  });

  it("only shows the steps to someone who cannot change them", () => {
    renderList(false);
    expect(screen.getByRole("button", { name: "Visa Steg 1: Sammanfatta" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Flytta/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Fler åtgärder/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Lägg till steg" })).toBeNull();
    // Suggestions are for editors: they are not asked for.
    expect(api.GET).not.toHaveBeenCalledWith("/api/v1/flows/{id}/suggestions/", expect.anything());
  });
});
