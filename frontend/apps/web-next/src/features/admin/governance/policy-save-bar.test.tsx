// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { PolicySaveBar } from "./policy-save-bar";

function renderBar(canSave: boolean, onSave = vi.fn()) {
  renderInApp(
    <>
      {/* A section's problem, as the governance sections mark it. */}
      <p role="alert" data-save-problem="" tabIndex={-1}>
        Välj minst en provider eller modell.
      </p>
      <PolicySaveBar
        dirty
        saveError={null}
        canSave={canSave}
        saving={false}
        onDiscard={() => {}}
        onSave={onSave}
      />
    </>
  );
  return { onSave, save: screen.getByRole("button", { name: "Spara ändringar" }) };
}

it("moves focus to the first problem instead of saving while one blocks it", () => {
  const { onSave, save } = renderBar(false);
  // Never disabled: a disabled button says nothing about what is missing.
  expect((save as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(save);

  expect(document.activeElement?.textContent).toBe("Välj minst en provider eller modell.");
  expect(onSave).not.toHaveBeenCalled();
});

it("saves once nothing blocks it", () => {
  const { onSave, save } = renderBar(true);
  fireEvent.click(save);
  expect(onSave).toHaveBeenCalledTimes(1);
});
