// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ReasoningEffortSelector } from "./reasoning-selector";

afterEach(cleanup);

const options = ["low", "medium", "high"];

function trigger() {
  return screen.getByRole("combobox", { name: /^Resonemangsnivå: / });
}

describe("ReasoningEffortSelector", () => {
  it("is named by the level in force: the organisation default, then the stored pick", () => {
    const { rerender } = renderInApp(
      <ReasoningEffortSelector
        options={options}
        stored={null}
        policyDefault={null}
        onSelect={vi.fn()}
      />
    );
    expect(screen.getByRole("combobox", { name: "Resonemangsnivå: Standard" })).toBeTruthy();

    rerender(
      <ReasoningEffortSelector
        options={options}
        stored={null}
        policyDefault="medium"
        onSelect={vi.fn()}
      />
    );
    expect(screen.getByRole("combobox", { name: "Resonemangsnivå: Medel" })).toBeTruthy();

    rerender(
      <ReasoningEffortSelector
        options={options}
        stored="high"
        policyDefault="medium"
        onSelect={vi.fn()}
      />
    );
    expect(screen.getByRole("combobox", { name: "Resonemangsnivå: Hög" })).toBeTruthy();
  });

  it("lists the organisation default (naming the policy's level) and the model's levels", async () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    renderInApp(
      <ReasoningEffortSelector
        options={options}
        stored={null}
        policyDefault="medium"
        onSelect={onSelect}
      />
    );
    fireEvent.click(trigger());
    const listbox = await screen.findByRole("listbox");
    const names = screen.getAllByRole("option").map((option) => option.textContent);
    expect(names[0]).toContain("Organisationens standard");
    expect(names[0]).toContain("Medel");
    expect(names.slice(1)).toEqual(["Låg", "Medel", "Hög"]);
    expect(listbox).toBeTruthy();

    fireEvent.click(screen.getByRole("option", { name: "Hög" }));
    expect(onSelect).toHaveBeenCalledWith("high");
    // The new level shows (and names the trigger) while it saves.
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Resonemangsnivå: Hög" })).toBeTruthy()
    );
  });

  it("saves null for the organisation default and opens from the keyboard", async () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    renderInApp(
      <ReasoningEffortSelector
        options={options}
        stored="low"
        policyDefault={null}
        onSelect={onSelect}
      />
    );
    const button = trigger();
    button.focus();
    fireEvent.keyDown(button, { key: "Enter" });
    const option = await screen.findByRole("option", { name: /Organisationens standard/ });
    fireEvent.click(option);
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("falls back to the stored level when the save fails", async () => {
    const onSelect = vi.fn().mockRejectedValue(new Error("nope"));
    renderInApp(
      <ReasoningEffortSelector
        options={options}
        stored="low"
        policyDefault={null}
        onSelect={onSelect}
      />
    );
    fireEvent.click(trigger());
    fireEvent.click(await screen.findByRole("option", { name: "Hög" }));
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Resonemangsnivå: Låg" })).toBeTruthy()
    );
  });

  it("has no axe violations closed and open", async () => {
    renderInApp(
      <ReasoningEffortSelector
        options={options}
        stored={null}
        policyDefault="medium"
        onSelect={vi.fn()}
      />
    );
    await expectNoAxeViolations(document.body);
    fireEvent.click(trigger());
    await screen.findByRole("listbox");
    await expectNoAxeViolations(document.body);
  });
});
