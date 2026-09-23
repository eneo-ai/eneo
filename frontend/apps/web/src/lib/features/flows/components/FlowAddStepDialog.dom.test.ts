import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
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

function checkedTemplates() {
  const group = screen.getByRole("radiogroup", { name: m.flow_add_step_templates_label() });
  return within(group)
    .getAllByRole("radio")
    .filter((radio) => radio.getAttribute("aria-checked") === "true");
}

describe("FlowAddStepDialog keyboard flow", () => {
  it("moves the selection with arrow keys from the search field", async () => {
    renderDialog();
    const search = screen.getByLabelText(m.flow_add_step_search());

    await fireEvent.keyDown(search, { key: "ArrowDown" });
    const checked = checkedTemplates();
    expect(checked).toHaveLength(1);

    await fireEvent.keyDown(search, { key: "ArrowDown" });
    const checkedAfter = checkedTemplates();
    expect(checkedAfter).toHaveLength(1);
    expect(checkedAfter[0]).not.toBe(checked[0]);
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

describe("FlowAddStepDialog document format", () => {
  it("keeps the chosen format when it is clicked again", async () => {
    renderDialog();
    await fireEvent.click(
      screen.getByRole("radio", { name: new RegExp(m.flow_template_document_name()) })
    );
    const format = screen.getByRole("group", { name: m.flow_add_step_format() });
    const pdf = within(format).getByRole("radio", { name: "PDF" });

    await fireEvent.click(pdf);
    expect(pdf.getAttribute("aria-checked")).toBe("true");
    // A second click on the chosen option used to clear the control while the
    // dialog kept creating a PDF step.
    await fireEvent.click(pdf);
    expect(pdf.getAttribute("aria-checked")).toBe("true");
  });
});
