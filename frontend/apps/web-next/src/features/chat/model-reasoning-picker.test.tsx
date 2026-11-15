// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNameToHoldVisibleText, expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
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
  });
});
