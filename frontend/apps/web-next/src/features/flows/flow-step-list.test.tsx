// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { focusManager, type QueryClient } from "@tanstack/react-query";
import { createRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowReferences } from "./chat/reference-pill";
import messages from "@/lib/i18n/messages/sv.json";
import { makeFlow, makeStep } from "./flow-fixtures";
import type { SuggestionDismissal, SuggestionFix } from "./flow-suggestion-item";

const state = vi.hoisted(() => ({ announce: vi.fn() }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

const prompts = vi.hoisted(() => ({
  byAssistant: {} as Record<string, string>,
  suggestions: [] as Record<string, unknown>[],
  // The answer measured over the latest runs (`?runs=`).
  measured: { runs: null as unknown, items: [] as unknown[] }
}));
const api = vi.hoisted(() => ({
  GET: vi.fn(
    async (
      path: string,
      init: { params: { path: { assistant_id: string }; query?: { runs?: number } } }
    ) => {
      if (path === "/api/v1/flows/{id}/suggestions/") {
        const runs = init.params.query?.runs;
        return {
          data: runs
            ? { flow_id: "flow-1", draft_revision: 4, ...prompts.measured }
            : { flow_id: "flow-1", draft_revision: 4, runs: null, items: prompts.suggestions },
          response: new Response(null, { status: 200 })
        };
      }
      const id = init.params.path.assistant_id;
      return {
        data: { id, prompt: { text: prompts.byAssistant[id] ?? "" } },
        response: new Response(null, { status: 200 })
      };
    }
  )
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { FlowStepList, type SpeakerStepOffer } from "./flow-step-list";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  prompts.byAssistant = {};
  prompts.suggestions = [];
  prompts.measured = { runs: null, items: [] };
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

/** The suggestion reads the list made, by the runs they measured (0 for none). */
function suggestionReads(): number[] {
  return api.GET.mock.calls
    .filter(([path]) => path === "/api/v1/flows/{id}/suggestions/")
    .map(([, init]) => init.params.query?.runs ?? 0);
}

/** `suggestionAbout`, measured over recent runs. */
function measuredAbout(
  stepId: string,
  fingerprint: string,
  impact: Record<string, unknown>,
  level = "high"
) {
  return {
    ...suggestionAbout(stepId, fingerprint, "assisted", level),
    impact: { basis: "runs", level, run_count: 8, version: 3, step_changed_since: false, ...impact }
  };
}

/**
 * The list with "Räkna med de senaste körningarna", the choice held as the
 * page holds it. `revision` is the draft revision on screen.
 */
function renderMeasured(revision = 4) {
  function Measured({ draftRevision }: { draftRevision: number }) {
    const [runs, setRuns] = useState(0);
    return (
      <FlowReferences flow={makeFlow({ steps })} onShowStep={() => true}>
        <FlowStepList
          flowId="flow-1"
          draftRevision={draftRevision}
          steps={steps}
          canEdit
          headingRef={createRef()}
          measure={{ runs, onMeasure: () => setRuns(10), onPlain: () => setRuns(0) }}
          onOpen={vi.fn()}
          onMove={vi.fn()}
          onRemove={vi.fn(async () => {})}
          onAdd={vi.fn()}
        />
      </FlowReferences>
    );
  }
  const view = renderInApp(<Measured draftRevision={revision} />);
  return { ...view, ui: (next: number) => <Measured draftRevision={next} /> };
}

/** A suggestion as the core lists it once an editor of the flow dismissed it. */
function dismissedBy<T extends Record<string, unknown>>(
  suggestion: T,
  by: string | null = "user-1"
) {
  return { ...suggestion, dismissed: { dismissed_by: by, dismissed_at: "2026-10-25T09:30:00Z" } };
}

/**
 * The list with "Ignorera" and "Visa ignorerade" as the page offers them: a
 * dismissal or a restore changes what the core answers and reads the
 * suggestions again, and the choice to show the dismissed ones is held as
 * the page holds it. `calls` records what was dismissed and restored.
 */
function renderDismissable(fix?: SuggestionFix) {
  const calls = { dismissed: [] as unknown[], restored: [] as unknown[] };
  let client: QueryClient | null = null;
  const reread = (fingerprint: string, dismiss: boolean) => {
    prompts.suggestions = prompts.suggestions.map((item) =>
      item.fingerprint !== fingerprint
        ? item
        : dismiss
          ? dismissedBy(item)
          : { ...item, dismissed: null }
    );
    return client!.invalidateQueries({ queryKey: ["flows", "flow-1", "suggestions"] });
  };
  function Dismissable() {
    const [showDismissed, setShowDismissed] = useState(false);
    const dismissal: SuggestionDismissal = {
      onDismiss: async (suggestion) => {
        calls.dismissed.push(suggestion);
        await reread(suggestion.fingerprint, true);
        return true;
      },
      onRestore: async (suggestion) => {
        calls.restored.push(suggestion);
        await reread(suggestion.fingerprint, false);
        return true;
      },
      busy: null,
      showDismissed,
      onShowDismissed: setShowDismissed
    };
    return (
      <FlowReferences flow={makeFlow({ steps })} onShowStep={() => true}>
        <FlowStepList
          flowId="flow-1"
          draftRevision={4}
          steps={steps}
          canEdit
          headingRef={createRef()}
          suggestionFix={fix}
          dismissal={dismissal}
          onOpen={vi.fn()}
          onMove={vi.fn()}
          onRemove={vi.fn(async () => {})}
          onAdd={vi.fn()}
        />
      </FlowReferences>
    );
  }
  const view = renderInApp(<Dismissable />);
  client = view.queryClient;
  return { ...view, calls };
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

  it("offers no measuring where the page does not, and reads no runs", async () => {
    prompts.suggestions = [suggestionAbout("step-2", "a".repeat(64))];
    renderList();
    expect(await screen.findByText(/förslag kan göra flödet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Räkna med de senaste körningarna" })).toBeNull();
    expect(suggestionReads()).toEqual([0]);
  });

  it("measures over the latest runs only when asked, and says what the numbers are based on", async () => {
    prompts.suggestions = [suggestionAbout("step-2", "a".repeat(64))];
    prompts.measured = {
      runs: { requested: 10, counted: 8, left_out: 2 },
      items: [
        measuredAbout("step-2", "a".repeat(64), { tokens_per_run: 1840 }),
        measuredAbout(
          "step-3",
          "c".repeat(64),
          { tokens_per_run: null, step_changed_since: true },
          "medium"
        )
      ]
    };
    const { container } = renderMeasured();
    const measure = await screen.findByRole("button", { name: "Räkna med de senaste körningarna" });
    // Nothing is measured until the person asks.
    expect(suggestionReads()).toEqual([0]);

    fireEvent.click(measure);
    expect(
      await screen.findByText(
        "Baserat på 8 körningar. 2 körningar räknades inte med eftersom du inte har behörighet att se dem."
      )
    ).toBeTruthy();
    expect(suggestionReads()).toEqual([0, 10]);
    // The same button offers the way back, so focus stays on it.
    expect(measure.textContent).toContain("Visa utan körningarna");
    expect(screen.getByRole("button", { name: "Visa utan körningarna" })).toBe(measure);

    // A measured row says what it costs without being opened.
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(within(second).getByRole("button", { name: "1 förslag" }));
    expect(
      within(second).getByText(
        "Kostar cirka 1 800 tokens per körning, mätt i 8 körningar av version 3."
      )
    ).toBeTruthy();
    const third = screen.getByRole("article", { name: "Steg 3 Granska" });
    fireEvent.click(within(third).getByRole("button", { name: "1 förslag" }));
    expect(
      within(third).getByText("Mätt i 8 körningar. Steget har ändrats sedan dess.")
    ).toBeTruthy();
    await expectNoAxeViolations(container);

    // Back to the definition alone: no runs are read, and no row is measured.
    fireEvent.click(measure);
    await waitFor(() => expect(screen.queryByText(/Baserat på/)).toBeNull());
    expect(within(second).queryByText(/Kostar cirka/)).toBeNull();
    expect(measure.textContent).toContain("Räkna med de senaste körningarna");
    expect(suggestionReads()).toEqual([0, 10]);
  });

  it("reads the measured answer again for a new revision, and never by itself", async () => {
    prompts.measured = {
      runs: { requested: 10, counted: 8, left_out: 0 },
      items: [measuredAbout("step-2", "a".repeat(64), { tokens_per_run: 400 })]
    };
    const { rerender, ui, unmount } = renderMeasured();
    fireEvent.click(
      await screen.findByRole("button", { name: "Räkna med de senaste körningarna" })
    );
    expect(await screen.findByText("Baserat på 8 körningar.")).toBeTruthy();
    expect(suggestionReads()).toEqual([0, 10]);

    // A window focus reads nothing again.
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    focusManager.setFocused(undefined);
    expect(suggestionReads()).toEqual([0, 10]);
    // A new revision is a new read, of that revision; the last answer stays meanwhile.
    rerender(ui(5));
    expect(screen.getByText("Baserat på 8 körningar.")).toBeTruthy();
    await waitFor(() => expect(suggestionReads()).toEqual([0, 10, 10]));
    expect(api.GET.mock.calls.at(-1)?.[1].params.query).toEqual({
      runs: 10,
      include_dismissed: true
    });
    unmount();
  });

  it("says when there are no finished runs to count, and keeps the way back with no suggestion", async () => {
    prompts.measured = { runs: { requested: 10, counted: 0, left_out: 0 }, items: [] };
    const { container } = renderMeasured();
    // No suggestion from the definition: only the action, no summary.
    const measure = await screen.findByRole("button", { name: "Räkna med de senaste körningarna" });
    expect(screen.queryByText(/förslag kan göra flödet/)).toBeNull();

    fireEvent.click(measure);
    expect(
      await screen.findByText("Inga förslag. Det finns inga avslutade körningar att räkna med än.")
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Visa utan körningarna" })).toBe(measure);
    await expectNoAxeViolations(container);
  });

  it("puts a measured overlap on its duplicate's row, and a forwarding finding's steps as pills", async () => {
    const duplicate = measuredAbout("step-2", "a".repeat(64), { tokens_per_run: 1840 });
    prompts.measured = {
      runs: { requested: 10, counted: 8, left_out: 0 },
      items: [
        {
          ...duplicate,
          params: {
            ...duplicate.params,
            measured_overlaps: [
              { shared_share: 0.62, shared_bytes: 3100, run_count: 5, held_runs: 4 }
            ]
          }
        },
        {
          code: "model_relay",
          fingerprint: "b".repeat(64),
          steps: ["step-2", "step-1", "step-3"],
          params: {
            producer_step_order: 1,
            producer_step_id: "step-1",
            reads: [{ channel: "input", site: "input_source", selector: [] }],
            readers: [{ step_order: 3, step_id: "step-3", sites: ["input_bindings.question"] }],
            copied_share: 0.83,
            input_share: 0.9,
            copied_bytes: 5400,
            run_count: 5,
            held_runs: 4
          },
          message: "Step 2 copies step 1.",
          impact: {
            basis: "runs",
            level: "high",
            tokens_per_run: 600,
            run_count: 5,
            version: 3,
            step_changed_since: false
          },
          fix: { kind: "assisted" }
        }
      ]
    };
    const { container } = renderMeasured();
    fireEvent.click(
      await screen.findByRole("button", { name: "Räkna med de senaste körningarna" })
    );
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(await within(second).findByRole("button", { name: "2 förslag" }));

    // One row per suggestion: the overlap is a line on the duplicate's row.
    const rows = within(second).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(
      within(rows[0]!).getByText(
        "Kostar cirka 1 800 tokens per körning, mätt i 8 körningar av version 3. " +
          "I 4 av de 5 senaste körningarna delade underlagen 62 % av texten."
      )
    ).toBeTruthy();
    expect(within(rows[1]!).getByText(/^Modellen skriver av svaret från/)).toBeTruthy();
    expect(within(rows[1]!).getByRole("button", { name: "Steg 1: Sammanfatta" })).toBeTruthy();
    fireEvent.click(within(rows[1]!).getByRole("button", { name: /^Mer om/ }));
    expect(within(rows[1]!).getByRole("button", { name: "Steg 3: Granska" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("lists a step's measured suggestions by their cost, then by level", async () => {
    prompts.measured = {
      runs: { requested: 10, counted: 8, left_out: 0 },
      items: [
        measuredAbout("step-2", "a".repeat(64), { tokens_per_run: null }, "high"),
        measuredAbout("step-2", "b".repeat(64), { tokens_per_run: 300 }, "low"),
        measuredAbout("step-2", "c".repeat(64), { tokens_per_run: 2500 }, "medium")
      ]
    };
    renderMeasured();
    fireEvent.click(
      await screen.findByRole("button", { name: "Räkna med de senaste körningarna" })
    );
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(await within(second).findByRole("button", { name: "3 förslag" }));
    expect(
      within(second)
        .getAllByRole("listitem")
        .map((row) => within(row).getByText(/^(Kostar|Mätt)/).textContent)
    ).toEqual([
      // The locale groups the digits (a no-break space in Swedish).
      "Kostar cirka 2\u00a0500 tokens per körning, mätt i 8 körningar av version 3.",
      "Kostar cirka 300 tokens per körning, mätt i 8 körningar av version 3.",
      "Mätt i 8 körningar."
    ]);
  });

  it("dismisses a suggestion from its row and keeps focus on the step it was about", async () => {
    prompts.suggestions = [suggestionAbout("step-2", "a".repeat(64), "patch")];
    const { calls } = renderDismissable();
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    fireEvent.click(
      await within(second).findByRole("button", { name: "1 förslag, 1 kan åtgärdas" })
    );
    // Nothing is dismissed yet: nothing offers to show what is.
    expect(screen.queryByRole("button", { name: /^Visa ignorerade/ })).toBeNull();
    fireEvent.click(within(second).getByRole("button", { name: /^Mer om/ }));

    const ignore = within(second).getByRole("button", {
      name: "Ignorera ”Svaret från Steg 1: Sammanfatta skickas två gånger”"
    });
    ignore.focus();
    fireEvent.click(ignore);

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_suggestion_dismissed_done)
    );
    expect(calls.dismissed).toEqual([
      expect.objectContaining({ code: "duplicate_read", fingerprint: "a".repeat(64) })
    ]);
    // The row left with its button: focus is on the step it was about, never on <body>.
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Redigera Steg 2: Skriv svar" })
      )
    );
    expect(within(second).queryByRole("button", { name: /förslag/ })).toBeNull();
    // Nothing counts it any more; it waits under "Visa ignorerade".
    expect(screen.queryByText(/förslag kan göra flödet/)).toBeNull();
    expect(screen.getByText("Förslaget är ignorerat")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Visa ignorerade (1)" })).toBeTruthy();
  });

  it("lists the dismissed suggestions with who and when, without a fix, and shows one again", async () => {
    prompts.suggestions = [
      dismissedBy(suggestionAbout("step-2", "a".repeat(64), "patch")),
      dismissedBy(UNUSED_FIELD, "user-2"),
      suggestionAbout("step-3", "c".repeat(64))
    ];
    const fix = { onFix: vi.fn(async () => true), pending: false };
    const { container, calls } = renderDismissable(fix);

    // Only the suggestion that is not dismissed counts, and nothing offers to fix the others.
    expect(
      await screen.findByText("1 förslag kan göra flödet enklare eller billigare")
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Åtgärda alla/ })).toBeNull();
    const second = screen.getByRole("article", { name: "Steg 2 Skriv svar" });
    expect(within(second).queryByRole("button", { name: /förslag/ })).toBeNull();

    const show = screen.getByRole("button", { name: "Visa ignorerade (2)" });
    expect(show.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(show);
    // The same button hides them again.
    expect(show.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: "Dölj ignorerade (2)" })).toBe(show);
    const panel = document.getElementById(show.getAttribute("aria-controls") ?? "")!;
    const rows = within(panel).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(
      within(rows[0]!)
        .getByText(/^Steg 2: Skriv svar · Ignorerat av dig ·/)
        .querySelector("time")
    ).toBeTruthy();
    expect(
      within(rows[1]!)
        .getByText(/^Körningens formulär · Ignorerat av en annan person ·/)
        .querySelector("time")
    ).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: /^Åtgärda/ })).toBeNull();
    expect(within(panel).queryByRole("button", { name: /^Ignorera/ })).toBeNull();
    await expectNoAxeViolations(container);

    const again = within(rows[0]!).getByRole("button", {
      name: "Visa ”Svaret från Steg 1: Sammanfatta skickas två gånger” igen"
    });
    again.focus();
    fireEvent.click(again);

    await waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_suggestion_restored_done)
    );
    expect(calls.restored).toEqual([expect.objectContaining({ fingerprint: "a".repeat(64) })]);
    // Back on its step's card; focus stays on the list of the one left.
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Dölj ignorerade (1)" })
      )
    );
    expect(within(second).getByRole("button", { name: "1 förslag, 1 kan åtgärdas" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dölj ignorerade (1)" }));
    expect(panel.hidden).toBe(true);
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
