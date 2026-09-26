// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { ModelSelector } from "./model-selector";

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
    id: "gpt-4o",
    name: "gpt-4o-2024-08-06",
    nickname: "GPT-4o",
    org: "OpenAI",
    vision: true,
    supports_tool_calling: true,
    input_cost_per_token: "0.0000025",
    output_cost_per_token: "0.00001"
  }),
  model({ id: "gpt-4o-mini", name: "gpt-4o-mini", nickname: "GPT-4o mini", org: "OpenAI" }),
  model({
    id: "sonnet",
    name: "claude-sonnet-4",
    nickname: "Claude Sonnet 4",
    org: "Anthropic",
    max_input_tokens: 200_000,
    reasoning: true
  })
];

afterEach(cleanup);

function renderSelector(props: Partial<React.ComponentProps<typeof ModelSelector>> = {}) {
  const onSelect = vi.fn();
  const view = renderInApp(
    <ModelSelector models={MODELS} selectedId="gpt-4o" onSelect={onSelect} {...props} />
  );
  return { onSelect, ...view };
}

function trigger() {
  return screen.getByRole("button", { name: /^Completion-modell: / });
}

describe("ModelSelector", () => {
  it("names the trigger by its label and the chosen model", async () => {
    const { container } = renderSelector();
    const button = screen.getByRole("button", { name: "Completion-modell: GPT-4o" });
    expect(button.getAttribute("aria-haspopup")).toBe("listbox");
    expect(button.getAttribute("aria-expanded")).toBe("false");
    await expectNoAxeViolations(container);
  });

  it("lists the models by vendor with their context, capabilities and prices as text", async () => {
    renderSelector({ showPricing: true });
    fireEvent.click(trigger());

    const listbox = await screen.findByRole("listbox");
    const vendors = within(listbox)
      .getAllByRole("group")
      .map((group) => group.getAttribute("aria-label"));
    expect(vendors).toEqual(["Anthropic", "OpenAI"]);

    const openai = within(listbox).getByRole("group", { name: "OpenAI" });
    const gpt = within(openai).getByRole("option", { name: /^GPT-4o\b(?! mini)/ });
    expect(gpt.getAttribute("aria-selected")).toBe("true");
    expect(gpt.textContent).toContain(
      "128K kontext · Vision · Verktyg · $2.50 / $10.00 per 1M tokens"
    );
    const sonnet = within(listbox).getByRole("option", { name: /Claude Sonnet 4/ });
    expect(sonnet.getAttribute("aria-selected")).toBe("false");
    expect(sonnet.textContent).toContain("200K kontext · Resonemang");
    await expectNoAxeViolations(document.body);
  });

  it("hides prices when the organisation does not show them", async () => {
    renderSelector({ showPricing: false });
    fireEvent.click(trigger());

    const gpt = await screen.findByRole("option", { name: /^GPT-4o\b(?! mini)/ });
    expect(gpt.textContent).toContain("128K kontext · Vision · Verktyg");
    expect(gpt.textContent).not.toContain("$");
  });

  it("searches models by name or vendor and picks one with the keyboard", async () => {
    const { onSelect } = renderSelector();
    const button = trigger();
    button.focus();
    fireEvent.keyDown(button, { key: "Enter" });

    const search = await screen.findByRole("combobox", { name: "Sökalternativ" });
    await waitFor(() => expect(document.activeElement).toBe(search));
    expect(search.getAttribute("placeholder")).toBe("Sök modeller och leverantörer");

    fireEvent.change(search, { target: { value: "anthropic" } });
    const options = screen.getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      expect.stringContaining("Claude Sonnet 4")
    ]);

    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(search.getAttribute("aria-activedescendant")).toBe(options[0]!.id);
    fireEvent.keyDown(search, { key: "Enter" });

    expect(onSelect).toHaveBeenCalledWith("sonnet");
    await waitFor(() => expect(document.activeElement).toBe(button));
    expect(button.getAttribute("aria-expanded")).toBe("false");

    fireEvent.keyDown(button, { key: "Enter" });
    const again = await screen.findByRole("combobox", { name: "Sökalternativ" });
    fireEvent.change(again, { target: { value: "finns inte" } });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("Inga modeller hittades")).toBeTruthy();
  });

  it("keeps focus on the trigger and shows the new model while it saves", async () => {
    let finishSave: () => void = () => {};
    const onSelect = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishSave = resolve;
        })
    );
    const { rerender } = renderInApp(
      <ModelSelector models={MODELS} selectedId="gpt-4o" onSelect={onSelect} size="sm" />
    );
    fireEvent.click(trigger());
    fireEvent.click(await screen.findByRole("option", { name: /Claude Sonnet 4/ }));

    const button = screen.getByRole("button", { name: "Completion-modell: Claude Sonnet 4" });
    await waitFor(() => expect(document.activeElement).toBe(button));
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect((button as HTMLButtonElement).disabled).toBe(false);

    rerender(<ModelSelector models={MODELS} selectedId="sonnet" onSelect={onSelect} size="sm" />);
    await act(async () => finishSave());
    expect(button.getAttribute("aria-busy")).toBeNull();
    expect(button.getAttribute("aria-label")).toBe("Completion-modell: Claude Sonnet 4");
  });

  it("goes back to the saved model when the save fails", async () => {
    const onSelect = vi.fn(() => Promise.reject(new Error("Nätverksfel")));
    renderInApp(<ModelSelector models={MODELS} selectedId="gpt-4o" onSelect={onSelect} />);
    fireEvent.click(trigger());
    fireEvent.click(await screen.findByRole("option", { name: /Claude Sonnet 4/ }));

    await waitFor(() =>
      expect(trigger().getAttribute("aria-label")).toBe("Completion-modell: GPT-4o")
    );
    expect(trigger().getAttribute("aria-busy")).toBeNull();
  });

  it("says when the saved model is no longer offered", () => {
    renderSelector({ selectedId: "retired-model" });
    expect(
      screen.getByRole("button", { name: "Completion-modell: Stöds ej vald modell" }).textContent
    ).toContain("Stöds ej vald modell");
  });

  it("shows a model pinned by the policy as a read-only field with the reason", async () => {
    const { container } = renderSelector({
      locked: { id: "gpt-4o", name: "gpt-4o", nickname: "GPT-4o", org: "OpenAI" }
    });
    const field = screen.getByRole("combobox", { name: "Completion-modell" });
    expect(field.getAttribute("aria-readonly")).toBe("true");
    expect(field.textContent).toContain("GPT-4o");
    const description = field
      .getAttribute("aria-describedby")!
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .join(" ");
    expect(description).toContain("Låst av administratör");

    fireEvent.click(field);
    expect(screen.queryByRole("listbox")).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("is a 44 px target on touch, and its rows are too", async () => {
    setViewport("phone");
    renderSelector({ size: "sm" });
    // An Astryx element size, which the theme makes 44 px on a coarse pointer.
    expect(trigger().closest("[data-size]")?.getAttribute("data-size")).toBe("md");
    fireEvent.click(trigger());

    // On a phone the list opens as a bottom sheet named by the field.
    const sheet = await screen.findByRole("dialog", { name: "Completion-modell" });
    const option = within(sheet).getAllByRole("option")[0]!;
    // The theme gives this Astryx part 44 px on a coarse pointer
    // (eneo-theme.ts → adaptations; globals-css.test.ts checks the CSS).
    expect(option.closest(".astryx-selector-option-row")).not.toBeNull();
  });
});
