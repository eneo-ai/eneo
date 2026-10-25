// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowReferences } from "./chat/reference-pill";
import { makeFlow, makeStep } from "./flow-fixtures";
import type { SuggestionFix } from "./flow-suggestion-item";

const state = vi.hoisted(() => ({ announce: vi.fn() }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

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

/** A `duplicate_read` about `stepId` (its first step): step 1 as its input and in its prompt. */
function suggestionAbout(stepId: string, fingerprint: string, kind = "assisted", level = "high") {
  return {
    code: "duplicate_read",
    fingerprint,
    steps: [stepId, "step-1"],
    params: {
      producer_step_order: 1,
      producer_step_id: "step-1",
      reads: [
        { channel: "input", site: "input_source", selector: [] },
        { channel: "prompt", site: "assistant_prompt:step_1.output.text", selector: [] }
      ]
    },
    message: "Reads step 1 twice.",
    impact: { basis: "definition", level },
    fix: { kind }
  };
}

const UNREAD_RESULT = {
  code: "unread_result",
  fingerprint: "e".repeat(64),
  steps: ["step-3"],
  params: {},
  message: "Nothing reads step 3.",
  impact: { basis: "definition", level: "medium" },
  fix: { kind: "advice" }
};

const UNUSED_FIELD = {
  code: "unused_form_field",
  fingerprint: "9".repeat(64),
  steps: [],
  params: { field: "Diarienummer" },
  message: "No step reads the field.",
  impact: { basis: "definition", level: "low" },
  fix: { kind: "patch" }
};

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

function renderList(
  canEdit = true,
  speakerOffer: SpeakerStepOffer | null = null,
  suggestionActions: { suggestionFix?: SuggestionFix; onAskChat?: (text: string) => void } = {}
) {
  const actions = {
    onOpen: vi.fn(),
    onMove: vi.fn(),
    onRemove: vi.fn(async () => {}),
    onAdd: vi.fn()
  };
  // The page's one FlowReferences, so references show as the chat's pills.
  const ui = (draftRevision: number) => (
    <FlowReferences flow={makeFlow({ steps })} onShowStep={() => true}>
      <FlowStepList
        flowId="flow-1"
        draftRevision={draftRevision}
        steps={steps}
        canEdit={canEdit}
        headingRef={createRef()}
        speakerOffer={speakerOffer}
        {...suggestionActions}
        {...actions}
      />
    </FlowReferences>
  );
  const view = renderInApp(ui(4));
  return { ...view, actions, ui };
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

  it("folds each step's suggestions into one quiet row with their count", async () => {
    prompts.suggestions = [
      suggestionAbout("step-2", "a".repeat(64), "patch"),
      suggestionAbout("step-2", "b".repeat(64), "assisted", "low"),
      suggestionAbout("step-3", "c".repeat(64)),
      // A step the draft no longer has shows nowhere.
      suggestionAbout("step-9", "d".repeat(64))
    ];
    const { container } = renderList();

    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    const toggle = await within(second).findByRole("button", {
      name: "2 förslag, 1 kan åtgärdas"
    });
    // The APG accordion: the button sits in a heading below the card's own.
    expect(toggle.closest("h4")).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "")!;
    expect(panel.hidden).toBe(true);
    const third = screen.getByRole("article", { name: "Steg 3 Granska" });
    expect(within(third).getByRole("button", { name: "1 förslag" })).toBeTruthy();
    const first = screen.getByRole("article", { name: "Steg 1 Sammanfatta" });
    expect(within(first).queryByRole("button", { name: /förslag/ })).toBeNull();
    // One request for the whole list.
    expect(
      api.GET.mock.calls.filter(([path]) => path === "/api/v1/flows/{id}/suggestions/")
    ).toHaveLength(1);
    await expectNoAxeViolations(container);
  });

  it("opens to rows by level, each with its own disclosure for why and what else", async () => {
    prompts.suggestions = [
      suggestionAbout("step-2", "a".repeat(64), "assisted", "low"),
      suggestionAbout("step-2", "b".repeat(64), "patch", "high"),
      { ...UNREAD_RESULT, steps: ["step-2"], fingerprint: "f".repeat(64) }
    ];
    const onAskChat = vi.fn();
    const { container } = renderList(true, null, { onAskChat });
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(await within(second).findByRole("button", { name: /^3 förslag/ }));

    const rows = within(second).getAllByRole("listitem");
    expect(rows.map((row) => within(row).getByText(/Stor|Medelstor|Liten/).textContent)).toEqual([
      "Stor påverkan",
      "Medelstor påverkan",
      "Liten påverkan"
    ]);
    // Collapsed rows show the title and nothing else.
    expect(within(second).queryByRole("button", { name: /^Fråga assistenten/ })).toBeNull();

    const more = within(rows[0]!).getByRole("button", {
      name: "Mer om ”Svaret från Steg 1: Sammanfatta skickas två gånger”"
    });
    fireEvent.click(more);
    expect(more.getAttribute("aria-expanded")).toBe("true");
    expect(within(rows[0]!).getByText(/Modellen läser den två gånger/)).toBeTruthy();
    // Steps and values are the chat's pills; a pill opens the reference card.
    fireEvent.click(within(rows[0]!).getByRole("button", { name: "Steg 1: Sammanfatta › text" }));
    expect(await screen.findByRole("dialog", { name: "Referens" })).toBeTruthy();
    fireEvent.click(
      within(rows[0]!).getByRole("button", {
        name: "Fråga assistenten om ”Svaret från Steg 1: Sammanfatta skickas två gånger”"
      })
    );
    expect(onAskChat).toHaveBeenCalledWith(
      expect.stringContaining("Steg: @[Skriv svar](step:step-2) @[Sammanfatta](step:step-1)")
    );
    // A step nothing reads offers the step list's own removal.
    fireEvent.click(within(rows[1]!).getByRole("button", { name: /^Mer om/ }));
    fireEvent.click(within(rows[1]!).getByRole("button", { name: "Ta bort Steg 2: Skriv svar" }));
    expect(await screen.findByRole("alertdialog", { name: "Ta bort steget?" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("keeps what was opened when the suggestions are read again", async () => {
    prompts.suggestions = [suggestionAbout("step-2", "a".repeat(64))];
    const { rerender, ui } = renderList();
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(await within(second).findByRole("button", { name: "1 förslag" }));
    fireEvent.click(within(second).getByRole("button", { name: /^Mer om/ }));

    // A new revision: read again, the same suggestion still there.
    rerender(ui(5));
    await waitFor(() =>
      expect(
        api.GET.mock.calls.filter(([path]) => path === "/api/v1/flows/{id}/suggestions/")
      ).toHaveLength(2)
    );
    expect(
      within(second).getByRole("button", { name: "1 förslag" }).getAttribute("aria-expanded")
    ).toBe("true");
    expect(
      within(second)
        .getByRole("button", { name: /^Mer om/ })
        .getAttribute("aria-expanded")
    ).toBe("true");

    // Gone from the draft, the step shows nothing.
    prompts.suggestions = [];
    rerender(ui(6));
    await waitFor(() =>
      expect(within(second).queryByRole("button", { name: "1 förslag" })).toBeNull()
    );
  });

  it("sums the suggestions up above the list, with the run form's own there", async () => {
    prompts.suggestions = [suggestionAbout("step-2", "a".repeat(64)), UNUSED_FIELD];
    renderList();

    expect(
      await screen.findByText("2 förslag kan göra flödet enklare eller billigare")
    ).toBeTruthy();
    const form = screen.getByRole("button", {
      name: "1 förslag om körningens formulär, 1 kan åtgärdas"
    });
    expect(form.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(form);
    expect(screen.getByText("Formulärfältet ”Diarienummer” används inte")).toBeTruthy();
    // Without a way to fix them, nothing offers to.
    expect(screen.queryByRole("button", { name: /^Åtgärda/ })).toBeNull();
  });

  it("shows no summary while the draft gives no suggestion", async () => {
    renderList();
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith("/api/v1/flows/{id}/suggestions/", expect.anything())
    );
    expect(screen.queryByText(/förslag kan göra flödet/)).toBeNull();
    expect(screen.queryByRole("button", { name: /förslag/ })).toBeNull();
  });

  it("fixes all patch suggestions after a confirmation that lists them by step", async () => {
    prompts.suggestions = [
      suggestionAbout("step-2", "a".repeat(64), "patch"),
      suggestionAbout("step-3", "c".repeat(64), "assisted"),
      UNUSED_FIELD
    ];
    const fix = { onFix: vi.fn(async () => true), pending: false };
    renderList(true, null, { suggestionFix: fix });

    fireEvent.click(await screen.findByRole("button", { name: "Åtgärda alla (2)" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Åtgärda 2 förslag?" });
    expect(within(dialog).getByText("Steg 2: Skriv svar")).toBeTruthy();
    expect(within(dialog).getByText("Körningens formulär")).toBeTruthy();
    expect(within(dialog).getByText("Steg 1: Sammanfatta")).toBeTruthy();
    expect(within(dialog).queryByText("Steg 3: Granska")).toBeNull();
    await expectNoAxeViolations(document.body);

    fireEvent.click(within(dialog).getByRole("button", { name: "Åtgärda" }));
    await waitFor(() => expect(fix.onFix).toHaveBeenCalledWith(["a".repeat(64), "9".repeat(64)]));
    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("2 förslag är åtgärdade"));
  });

  it("fixes one suggestion from its row, and offers no fix for an advice", async () => {
    prompts.suggestions = [suggestionAbout("step-2", "a".repeat(64), "patch"), UNREAD_RESULT];
    const fix = { onFix: vi.fn(async () => true), pending: false };
    renderList(true, null, { suggestionFix: fix });

    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(
      await within(second).findByRole("button", { name: "1 förslag, 1 kan åtgärdas" })
    );
    fireEvent.click(
      within(second).getByRole("button", {
        name: "Åtgärda ”Svaret från Steg 1: Sammanfatta skickas två gånger”"
      })
    );
    await waitFor(() => expect(fix.onFix).toHaveBeenCalledWith(["a".repeat(64)]));
    await waitFor(() => expect(state.announce).toHaveBeenCalledWith("Förslaget är åtgärdat"));

    const third = screen.getByRole("article", { name: "Steg 3 Granska" });
    fireEvent.click(within(third).getByRole("button", { name: "1 förslag" }));
    expect(within(third).queryByRole("button", { name: /^Åtgärda/ })).toBeNull();
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
