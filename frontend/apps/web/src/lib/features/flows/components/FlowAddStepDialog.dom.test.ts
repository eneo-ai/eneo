import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

import FlowAddStepDialog from "./FlowAddStepDialog.svelte";

function renderDialog(onConfirm = vi.fn()) {
  render(FlowAddStepDialog, {
    props: { open: true, previousOutputType: "text", onConfirm }
  });
  return onConfirm;
}

afterEach(() => {
  cleanup();
});

describe("FlowAddStepDialog keyboard flow", () => {
  it("moves the selection with arrow keys from the search field", async () => {
    renderDialog();
    const search = screen.getByLabelText(m.flow_add_step_search());

    await fireEvent.keyDown(search, { key: "ArrowDown" });
    const pressed = screen
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressed).toHaveLength(1);

    await fireEvent.keyDown(search, { key: "ArrowDown" });
    const pressedAfter = screen
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(pressedAfter).toHaveLength(1);
    expect(pressedAfter[0]).not.toBe(pressed[0]);
  });

  it("confirms the arrow-selected template with Enter", async () => {
    const onConfirm = renderDialog();
    const search = screen.getByLabelText(m.flow_add_step_search());

    await fireEvent.keyDown(search, { key: "ArrowDown" });
    await fireEvent.keyDown(search, { key: "Enter" });

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0]?.[0]).not.toBeNull();
  });

  it("announces the selected template to screen readers", async () => {
    renderDialog();
    const search = screen.getByLabelText(m.flow_add_step_search());
    const status = screen.getByRole("status");
    expect(status.textContent?.trim()).toBe("");

    await fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(status.textContent?.trim()).not.toBe("");
  });
});
