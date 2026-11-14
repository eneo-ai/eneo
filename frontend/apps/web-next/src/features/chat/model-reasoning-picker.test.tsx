// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNameToHoldVisibleText, expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { ModelReasoningPicker, type ModelReasoningPickerProps } from "./model-reasoning-picker";

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
  const onSelectModel = vi.fn(() => Promise.resolve());
  const onSelectLevel = vi.fn(() => Promise.resolve());
  renderInApp(
    <ModelReasoningPicker
      models={MODELS}
      selectedId="model-a"
      onSelectModel={onSelectModel}
      storedLevel={null}
      policyDefaultLevel="medium"
      onSelectLevel={onSelectLevel}
      {...props}
    />
  );
  return { onSelectModel, onSelectLevel };
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
    const { onSelectLevel, onSelectModel } = renderPicker();
    const panel = await openPanel();

    const levels = within(panel).getByRole("radiogroup", { name: "Resonemangsnivå" });
    expect(
      within(levels)
        .getAllByRole("radio")
        .map((radio) => radio.getAttribute("value"))
    ).toEqual(["low", "medium", "high"]);
    // The organisation's level is listed once, marked as the default and chosen.
    expect(
      within(levels).getByRole("radio", { name: "Medel Standard", checked: true })
    ).toBeTruthy();

    fireEvent.click(within(levels).getByRole("radio", { name: "Hög" }));
    // Shown at once, saved once the choice has rested.
    expect(
      screen.getByRole("button", { name: "Chattmodell: Modell A · Hög resonemangsnivå" })
    ).toBeTruthy();
    await waitFor(() => expect(onSelectLevel).toHaveBeenCalledWith("high"));
    expect(onSelectModel).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Chattmodell" })).toBeTruthy();
    await expectNoAxeViolations(panel);
  });

  it("saves null for the organisation's default level", async () => {
    const { onSelectLevel } = renderPicker({ storedLevel: "high" });
    const panel = await openPanel();
    fireEvent.click(within(panel).getByRole("radio", { name: "Medel Standard" }));
    await waitFor(() => expect(onSelectLevel).toHaveBeenCalledWith(null));
  });

  it("offers the model's own behaviour as the default when the organisation sets none", async () => {
    const { onSelectLevel } = renderPicker({ policyDefaultLevel: null, storedLevel: "low" });
    const panel = await openPanel("Chattmodell: Modell A · Låg resonemangsnivå");
    const levels = within(panel).getByRole("radiogroup", { name: "Resonemangsnivå" });
    expect(within(levels).getAllByRole("radio")).toHaveLength(4);
    fireEvent.click(within(levels).getByRole("radio", { name: "Standard" }));
    await waitFor(() => expect(onSelectLevel).toHaveBeenCalledWith(null));
  });

  it("saves the model the choice rests on, at once when the panel closes", async () => {
    const { onSelectModel } = renderPicker();
    const panel = await openPanel();
    const models = within(panel).getByRole("radiogroup", { name: "Chattmodell" });
    fireEvent.click(within(models).getByRole("radio", { name: /Modell B/ }));
    expect(onSelectModel).not.toHaveBeenCalled();

    fireEvent.keyDown(panel, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: /^Chattmodell: Modell B/ }));
    await waitFor(() => expect(onSelectModel).toHaveBeenCalledWith("model-b"));
    expect(onSelectModel).toHaveBeenCalledTimes(1);
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
    const { onSelectLevel } = renderPicker({ locked: MODELS[0] });
    const panel = await openPanel();
    expect(within(panel).queryByRole("radiogroup", { name: "Chattmodell" })).toBeNull();
    expect(within(panel).getByText("Låst av administratör")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("radio", { name: "Låg" }));
    await waitFor(() => expect(onSelectLevel).toHaveBeenCalledWith("low"));
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
});
