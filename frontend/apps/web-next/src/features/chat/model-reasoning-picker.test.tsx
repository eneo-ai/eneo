// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNameToHoldVisibleText, expectNoAxeViolations } from "@/test/axe";
import { flushAnnouncements, recordAnnouncements, renderInApp } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
import {
  ModelReasoningPicker,
  type ModelReasoningChange,
  type ModelReasoningPickerProps
} from "./model-reasoning-picker";

type CompletionModel = Schema<"CompletionModelPublic">;

function model(overrides: Partial<CompletionModel>): CompletionModel {
  return {
    id: "model",
    name: "model",
    max_input_tokens: 128_000,
    max_output_tokens: 4_096,
    is_deprecated: false,
    vision: false,
    reasoning: false,
    supports_tool_calling: false,
    ...overrides
  } as CompletionModel;
}

const MODELS = [
  model({
    id: "model-a",
    name: "model-a",
    nickname: "Modell A",
    org: "Leverantör A",
    reasoning: true,
    supported_model_kwargs: {
      reasoning_effort: { supported: true, control: "select", options: ["low", "medium", "high"] }
    }
  }),
  model({ id: "model-b", name: "model-b", nickname: "Modell B", org: "Leverantör B" })
];

afterEach(() => {
  cleanup();
  setViewport("desktop");
});

function renderPicker(props: Partial<ModelReasoningPickerProps> = {}) {
  const onSave = vi.fn<(change: ModelReasoningChange) => Promise<void>>(() => Promise.resolve());
  renderInApp(
    <ModelReasoningPicker
      models={MODELS}
      selectedId="model-a"
      storedLevel={null}
      policyDefaultLevel="medium"
      onSave={onSave}
      {...props}
    />
  );
  return { onSave };
}

async function openPanel(name: string | RegExp = /^Chattmodell: /) {
  fireEvent.click(screen.getByRole("button", { name }));
  return screen.findByRole("dialog", { name: "Chattmodell" });
}

describe("ModelReasoningPicker", () => {
  it("shows the model alone on the organisation's default level, and names a chosen level", () => {
    renderPicker();
    const plain = screen.getByRole("button", { name: "Chattmodell: Modell A" });
    expectNameToHoldVisibleText(plain, "Chattmodell: Modell A");
    cleanup();

    renderPicker({ storedLevel: "high" });
    const name = "Chattmodell: Modell A · Hög resonemangsnivå";
    expectNameToHoldVisibleText(screen.getByRole("button", { name }), name);
  });

  it("keeps a chosen level in view on a phone, where the logo stands for the model", () => {
    renderPicker({ storedLevel: "high" });
    const pill = screen.getByRole("button", { name: /^Chattmodell: / });
    // Tailwind's phone classes do not apply in the test DOM, so the classes are the evidence.
    expect(within(pill).getByText("Modell A").className).toMatch(/max-sm:sr-only/);
    expect(within(pill).getByText("Hög").className).not.toMatch(/sr-only/);
  });

  it("offers the model's levels beside the models and saves a level without closing", async () => {
    const { onSave } = renderPicker();
    const panel = await openPanel();

    const levels = within(panel).getByRole("radiogroup", { name: "Resonemangsnivå" });
    expect(
      within(levels)
        .getAllByRole("radio")
        .map((radio) => radio.getAttribute("value"))
    ).toEqual(["default", "low", "medium", "high"]);
    // Following the organisation: its default, with the level it is now, is chosen.
    expect(
      within(levels).getByRole("radio", { name: "Standard Medel", checked: true })
    ).toBeTruthy();

    fireEvent.click(within(levels).getByRole("radio", { name: "Hög" }));
    // Shown at once, saved once the choice has rested.
    expect(
      screen.getByRole("button", { name: "Chattmodell: Modell A · Hög resonemangsnivå" })
    ).toBeTruthy();
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ level: "high" }));
    expect(screen.getByRole("dialog", { name: "Chattmodell" })).toBeTruthy();
    await expectNoAxeViolations(panel);
  });

  it("saves null for the organisation's default level", async () => {
    const { onSave } = renderPicker({ storedLevel: "high" });
    const panel = await openPanel();
    fireEvent.click(within(panel).getByRole("radio", { name: "Standard Medel" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ level: null }));
  });

  it("tells an own level that equals the default apart, and lets it go back to following the default", async () => {
    const onSave = vi.fn(() => Promise.resolve());
    const picker = (storedLevel: string | null, policyDefaultLevel: string) => (
      <ModelReasoningPicker
        models={MODELS}
        selectedId="model-a"
        storedLevel={storedLevel}
        policyDefaultLevel={policyDefaultLevel}
        onSave={onSave}
      />
    );
    const view = renderInApp(picker("medium", "medium"));
    // The account has a level of its own, the same as the organisation's.
    const panel = await openPanel("Chattmodell: Modell A · Medel resonemangsnivå");
    const levels = within(panel).getByRole("radiogroup", { name: "Resonemangsnivå" });
    expect(within(levels).getByRole("radio", { name: "Medel", checked: true })).toBeTruthy();
    expect(
      within(levels).getByRole("radio", { name: "Standard Medel", checked: false })
    ).toBeTruthy();

    fireEvent.click(within(levels).getByRole("radio", { name: "Standard Medel" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ level: null }));

    // Saved as no level of its own, it follows when the organisation changes its default.
    view.rerender(picker(null, "high"));
    await waitFor(() =>
      expect(
        within(levels).getByRole("radio", { name: "Standard Hög", checked: true })
      ).toBeTruthy()
    );
    expect(screen.getByRole("button", { name: "Chattmodell: Modell A" })).toBeTruthy();
  });

  it("offers the model's own behaviour as the default when the organisation sets none", async () => {
    const { onSave } = renderPicker({ policyDefaultLevel: null, storedLevel: "low" });
    const panel = await openPanel("Chattmodell: Modell A · Låg resonemangsnivå");
    const levels = within(panel).getByRole("radiogroup", { name: "Resonemangsnivå" });
    expect(within(levels).getAllByRole("radio")).toHaveLength(4);
    fireEvent.click(within(levels).getByRole("radio", { name: "Standard" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ level: null }));
  });

  it("saves the model the choice rests on, at once when the panel closes", async () => {
    const { onSave } = renderPicker();
    const panel = await openPanel();
    const models = within(panel).getByRole("radiogroup", { name: "Chattmodell" });
    fireEvent.click(within(models).getByRole("radio", { name: /Modell B/ }));
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.keyDown(panel, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: /^Chattmodell: Modell B/ }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ modelId: "model-b" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("keeps the level's place and says so for a model without levels", async () => {
    renderPicker({ selectedId: "model-b", storedLevel: "high" });
    // A stored level the model does not offer is not in force.
    const panel = await openPanel("Chattmodell: Modell B");
    expect(within(panel).queryByRole("radiogroup", { name: "Resonemangsnivå" })).toBeNull();
    expect(within(panel).getByText("Den här modellen har inga resonemangsnivåer.")).toBeTruthy();
  });

  it("has no search for a short list, and finds a model by name or provider in a long one", async () => {
    renderPicker();
    expect(within(await openPanel()).queryByLabelText("Sök modeller och leverantörer")).toBeNull();
    cleanup();

    const more = Array.from({ length: 6 }, (_, index) =>
      model({ id: `extra-${index}`, name: `extra-${index}`, org: "Annan" })
    );
    renderPicker({ models: [...MODELS, ...more] });
    const panel = await openPanel();
    fireEvent.change(within(panel).getByLabelText("Sök modeller och leverantörer"), {
      target: { value: "leverantör b" }
    });
    const models = within(panel).getByRole("radiogroup", { name: "Chattmodell" });
    expect(within(models).getAllByRole("radio")).toHaveLength(1);
    fireEvent.change(within(panel).getByLabelText("Sök modeller och leverantörer"), {
      target: { value: "saknas" }
    });
    expect(within(panel).getByText("Inga modeller hittades")).toBeTruthy();
  });

  it("heads both columns at the top, with the search under the model column's heading", async () => {
    const more = Array.from({ length: 6 }, (_, index) =>
      model({ id: `extra-${index}`, name: `extra-${index}`, org: "Annan" })
    );
    renderPicker({ models: [...MODELS, ...more], storedLevel: "high" });
    const panel = await openPanel();
    const models = within(panel).getByRole("radiogroup", { name: "Chattmodell" });
    const levels = within(panel).getByRole("radiogroup", { name: "Resonemangsnivå" });
    const search = within(panel).getByLabelText("Sök modeller och leverantörer");
    // The model column's heading stands above the search, out of the list that scrolls.
    const heading = within(panel).getByText("Chattmodell", { selector: "p" });
    expect(heading.compareDocumentPosition(search) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(models.contains(heading)).toBe(false);
    // The groups keep their names; the level column's heading is its group's own label.
    expect(document.getElementById(levels.getAttribute("aria-labelledby")!)?.textContent).toBe(
      "Resonemangsnivå"
    );
    await expectNoAxeViolations(panel);
  });

  it("says how many models a search finds, and when it finds none", async () => {
    const said = recordAnnouncements();
    const more = Array.from({ length: 6 }, (_, index) =>
      model({ id: `extra-${index}`, name: `extra-${index}`, org: "Annan" })
    );
    renderPicker({ models: [...MODELS, ...more] });
    const panel = await openPanel();
    const search = within(panel).getByLabelText("Sök modeller och leverantörer");
    fireEvent.change(search, { target: { value: "leverantör b" } });
    await flushAnnouncements();
    fireEvent.change(search, { target: { value: "saknas" } });
    await flushAnnouncements();
    expect(said).toEqual(["1 modell hittad", "Inga modeller hittades"]);
  });

  it("brings the chosen model into view as the panel opens", async () => {
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView");
    try {
      const more = Array.from({ length: 8 }, (_, index) =>
        model({ id: `extra-${index}`, name: `extra-${index}`, org: "Annan" })
      );
      renderPicker({ models: [...more, ...MODELS], selectedId: "model-b" });
      const panel = await openPanel();
      const chosen = within(panel).getByRole("radio", { name: /Modell B/, checked: true });
      await waitFor(() =>
        expect(
          scrolled.mock.contexts.some((element) => (element as Element).contains(chosen))
        ).toBe(true)
      );
    } finally {
      scrolled.mockRestore();
    }
  });

  it("brings the chosen model into view each time a phone's sheet opens", async () => {
    setViewport("phone");
    const scrolled = vi.spyOn(Element.prototype, "scrollIntoView");
    try {
      const more = Array.from({ length: 8 }, (_, index) =>
        model({ id: `extra-${index}`, name: `extra-${index}`, org: "Annan" })
      );
      renderPicker({ models: [...more, ...MODELS], selectedId: "model-b" });
      // The sheet keeps its content while closed: what ran at mount, on a hidden list, does not count.
      await act(() => new Promise((done) => requestAnimationFrame(done)));
      const broughtIntoView = () => {
        const chosen = screen.getByRole("radio", { name: /Modell B/, checked: true, hidden: true });
        return scrolled.mock.contexts.some((element) => (element as Element).contains(chosen));
      };
      for (const time of ["first", "again"]) {
        scrolled.mockClear();
        const sheet = await openPanel();
        await waitFor(() => expect(broughtIntoView(), time).toBe(true));
        fireEvent.click(within(sheet).getByRole("button", { name: "Stäng" }));
        await waitFor(() =>
          expect(screen.queryByRole("dialog", { name: "Chattmodell" })).toBeNull()
        );
      }
    } finally {
      scrolled.mockRestore();
    }
  });

  it("fits the panel between the window's top margin and its pill, also over the chat's header", async () => {
    renderInApp(
      <div id="chat-panel-chat">
        <ModelReasoningPicker
          models={MODELS}
          selectedId="model-a"
          storedLevel={null}
          policyDefaultLevel={null}
          onSave={vi.fn()}
        />
      </div>
    );
    // The chat's panel starts under its header, 117 px down; the pill is 400 px down.
    vi.spyOn(document.getElementById("chat-panel-chat")!, "getBoundingClientRect").mockReturnValue(
      DOMRect.fromRect({ x: 0, y: 117, width: 1000, height: 700 })
    );
    const pill = vi
      .spyOn(screen.getByRole("button", { name: /^Chattmodell/ }), "getBoundingClientRect")
      .mockReturnValue(DOMRect.fromRect({ x: 600, y: 400, width: 160, height: 32 }));
    const panel = await openPanel();
    const fitted = panel.querySelector<HTMLElement>("[style*='max-height']")!;
    // 400 less the window's 16 px margin and the popover's 28 px of gap and padding: a list
    // that fits there never scrolls, even where the panel then covers the header.
    expect(fitted.style.maxHeight).toBe("356px");

    // The page around the composer settles while the panel is open (a list or the context
    // meter comes in) and the pill moves 16 px up: the room shrinks with it.
    pill.mockReturnValue(DOMRect.fromRect({ x: 600, y: 384, width: 160, height: 32 }));
    act(() => reportResize(document.getElementById("chat-panel-chat")!, { height: 716 }));
    expect(fitted.style.maxHeight).toBe("340px");
  });

  it("shows a pinned model read-only and still lets the level be chosen", async () => {
    const { onSave } = renderPicker({ locked: MODELS[0] });
    const panel = await openPanel();
    expect(within(panel).queryByRole("radiogroup", { name: "Chattmodell" })).toBeNull();
    expect(within(panel).getByText("Låst av administratör")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("radio", { name: "Låg" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ level: "low" }));
  });

  it("opens in a bottom sheet on a phone", async () => {
    setViewport("phone");
    renderPicker();
    const sheet = await openPanel();
    expect(sheet.tagName).toBe("DIALOG");
    expect(within(sheet).getByRole("radiogroup", { name: "Resonemangsnivå" })).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: "Stäng" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Chattmodell" })).toBeNull());
  });

  describe("a model and a level chosen together", () => {
    /** A model without levels, the one in use; one with levels; another without. */
    const RACE_MODELS = [
      model({ id: "plain", name: "plain", nickname: "Enkel" }),
      MODELS[0]!,
      model({ id: "delta", name: "delta", nickname: "Delta" })
    ];

    function deferred() {
      let resolve!: () => void;
      let reject!: (error: Error) => void;
      const promise = new Promise<void>((done, fail) => {
        resolve = done;
        reject = fail;
      });
      return { promise, resolve, reject };
    }

    async function choose(panel: HTMLElement, name: string | RegExp) {
      fireEvent.click(within(panel).getByRole("radio", { name }));
    }

    afterEach(() => vi.useRealTimers());

    it("saves one model without a level when the level was for a model passed over", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { onSave } = renderPicker({ models: RACE_MODELS, selectedId: "plain" });
      const panel = await openPanel("Chattmodell: Enkel");
      await choose(panel, /Modell A/);
      await choose(panel, "Låg");
      await choose(panel, /Delta/);
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(onSave.mock.calls).toEqual([[{ modelId: "delta" }]]);
    });

    it("saves a model and its level in one update", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { onSave } = renderPicker({ models: RACE_MODELS, selectedId: "plain" });
      const panel = await openPanel("Chattmodell: Enkel");
      await choose(panel, /Modell A/);
      await choose(panel, "Hög");
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(onSave.mock.calls).toEqual([[{ modelId: "model-a", level: "high" }]]);
    });

    it.each(["lands", "is refused"])(
      "shows the last choice until its own save is done when an earlier save %s",
      async (outcome) => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        const saves = [deferred(), deferred()];
        const onSave = vi.fn(() => saves[onSave.mock.calls.length - 1]!.promise);
        renderPicker({ models: RACE_MODELS, selectedId: "plain", onSave });
        const panel = await openPanel("Chattmodell: Enkel");
        const pill = () => screen.getByRole("button", { name: /^Chattmodell: / });

        await choose(panel, /Delta/);
        await act(() => vi.advanceTimersByTimeAsync(300));
        await choose(panel, /Enkel/);
        await act(() => vi.advanceTimersByTimeAsync(300));
        expect(onSave.mock.calls).toEqual([[{ modelId: "delta" }], [{ modelId: "plain" }]]);

        await act(async () => {
          if (outcome === "lands") saves[0]!.resolve();
          else saves[0]!.reject(new Error("refused"));
          await saves[0]!.promise.catch(() => {});
        });
        // The older save is done: the newer choice is still shown, still saving.
        expect(pill().getAttribute("aria-label")).toBe("Chattmodell: Enkel");
        expect(pill().getAttribute("aria-busy")).toBe("true");

        await act(async () => {
          saves[1]!.resolve();
          await saves[1]!.promise;
        });
        expect(pill().getAttribute("aria-label")).toBe("Chattmodell: Enkel");
        expect(pill().getAttribute("aria-busy")).toBeNull();
      }
    );

    /** Two models with levels, the first in use on Låg. */
    const LEVEL_MODELS = [
      MODELS[0]!,
      model({
        id: "model-c",
        name: "model-c",
        nickname: "Modell C",
        reasoning: true,
        supported_model_kwargs: MODELS[0]!.supported_model_kwargs
      })
    ];

    it("sends a level chosen while the model's save is open together with that model", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const saves = [deferred(), deferred()];
      const onSave = vi.fn(() => saves[onSave.mock.calls.length - 1]!.promise);
      renderPicker({ models: LEVEL_MODELS, storedLevel: "low", onSave });
      const panel = await openPanel();
      await choose(panel, /Modell C/);
      await act(() => vi.advanceTimersByTimeAsync(300));
      await choose(panel, "Hög");
      await act(() => vi.advanceTimersByTimeAsync(300));
      // Were the model's save refused, the level is still checked against Modell C, not stored on Modell A.
      expect(onSave.mock.calls).toEqual([
        [{ modelId: "model-c" }],
        [{ modelId: "model-c", level: "high" }]
      ]);
      await act(async () => {
        saves[0]!.reject(new Error("refused"));
        saves[1]!.resolve();
        await saves[1]!.promise;
      });
    });

    it("sends the level with the model chosen last while two model saves are open", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const onSave = vi.fn(() => new Promise<void>(() => {}));
      renderPicker({ models: LEVEL_MODELS, storedLevel: "low", onSave });
      const panel = await openPanel();
      await choose(panel, /Modell C/);
      await act(() => vi.advanceTimersByTimeAsync(300));
      await choose(panel, /Modell A/);
      await act(() => vi.advanceTimersByTimeAsync(300));
      await choose(panel, "Hög");
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(onSave.mock.calls.at(-1)).toEqual([{ modelId: "model-a", level: "high" }]);
    });

    it("never sends a pinned model, also with a level's save open", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const onSave = vi.fn(() => new Promise<void>(() => {}));
      renderPicker({ models: LEVEL_MODELS, locked: MODELS[0], storedLevel: "low", onSave });
      const panel = await openPanel();
      await choose(panel, "Hög");
      await act(() => vi.advanceTimersByTimeAsync(300));
      await choose(panel, "Medel");
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(onSave.mock.calls).toEqual([[{ level: "high" }], [{ level: "medium" }]]);
    });

    it("sends nothing for a rest that ends where it began, also with a model's save open", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const onSave = vi.fn(() => new Promise<void>(() => {}));
      renderPicker({ models: LEVEL_MODELS, storedLevel: "low", onSave });
      const panel = await openPanel();
      await choose(panel, /Modell C/);
      await act(() => vi.advanceTimersByTimeAsync(300));
      await choose(panel, "Hög");
      await choose(panel, "Låg");
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(onSave.mock.calls).toEqual([[{ modelId: "model-c" }]]);
    });

    it("with no save open, a rest sends only what it changed", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { onSave } = renderPicker({ models: LEVEL_MODELS, storedLevel: "low" });
      const panel = await openPanel();
      // There and back within one rest: nothing.
      await choose(panel, /Modell C/);
      await choose(panel, /Modell A/);
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(onSave).not.toHaveBeenCalled();
      // A level alone, then a model once that save has settled: each its own part.
      await choose(panel, "Hög");
      await act(() => vi.advanceTimersByTimeAsync(300));
      await choose(panel, /Modell C/);
      await act(() => vi.advanceTimersByTimeAsync(300));
      expect(onSave.mock.calls).toEqual([[{ level: "high" }], [{ modelId: "model-c" }]]);
    });
  });
});
