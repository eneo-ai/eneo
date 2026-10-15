import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import type { FlowStep } from "@eneo/eneo-js";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { flowStepFixture } from "$lib/features/flows/flowStepTestFixture";
import {
  parseAdvancedJsonField,
  syncDraftsFromStep,
  type AdvancedJsonField
} from "./advancedJsonDrafts";
import {
  EXAMPLE_MAX_CHARACTERS,
  EXAMPLE_MAX_FIELDS
} from "$lib/features/flows/outputContractFromExample";
import FlowStepAdvancedSection from "./FlowStepAdvancedSection.svelte";
import VariablePicker from "./VariablePicker.svelte";

// The section slides in and the picker scrolls its active option into view;
// jsdom has neither animation nor scrolling.
beforeAll(() => {
  Element.prototype.animate ??= (() => ({
    cancel() {},
    finished: Promise.resolve(),
    onfinish: null
  })) as never;
  Element.prototype.scrollIntoView ??= vi.fn();
});

afterEach(async () => {
  cleanup();
  await vi.waitFor(() => expect(document.body.style.overflow).not.toBe("hidden"));
});

type FieldUpdate = { field: AdvancedJsonField; value: string };

function renderSection(step: FlowStep) {
  const onJsonFieldUpdate = vi.fn<(detail: FieldUpdate) => void>();
  const { drafts, errors } = syncDraftsFromStep(step);
  const { rerender } = render(FlowStepAdvancedSection, {
    step,
    isPublished: false,
    advancedJsonDrafts: drafts,
    advancedJsonErrors: errors,
    onJsonFieldUpdate
  });
  // The editor's part: store what the section reports as the draft.
  onJsonFieldUpdate.mockImplementation(({ field, value }) =>
    rerender({ advancedJsonDrafts: { ...drafts, [field]: value } })
  );
  return onJsonFieldUpdate;
}

async function openWithExample(outputContract: FlowStep["output_contract"], example: string) {
  const step = flowStepFixture({ output_type: "json", output_contract: outputContract });
  const onCreate = renderSection(step);
  const trigger = screen.getByRole("button", { name: m.flow_contract_example_button() });
  // jsdom does not focus a clicked button; a browser does.
  trigger.focus();
  await fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog");
  await fireEvent.input(within(dialog).getByLabelText(m.flow_contract_example_label()), {
    target: { value: example }
  });
  const create = within(dialog).getByRole("button", { name: m.flow_contract_example_create() });
  return { step, onCreate, dialog, create };
}

describe("FlowOutputContractFromExample", () => {
  // Kills: the preview not naming the fields or their types, a contract that
  // the editor's own reader refuses, and a contract whose fields the variable
  // picker does not offer to a later step.
  it("previews the fields and writes a contract whose fields a later step can pick", async () => {
    const { step, onCreate, dialog, create } = await openWithExample(
      null,
      '{"anomaly_days": ["2026-01-02"], "total": 4}'
    );
    const preview = within(dialog).getByRole("list", {
      name: m.flow_contract_example_preview()
    });
    expect(preview.textContent).toContain("anomaly_days");
    expect(preview.textContent).toContain(
      m.flow_contract_example_type_list({ item: m.flow_contract_example_type_string() })
    );
    expect(preview.textContent).toContain(m.flow_contract_example_type_number());
    expect(within(dialog).queryByText(m.flow_contract_example_not_variable())).toBeNull();

    await fireEvent.click(create);
    expect(onCreate).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alertdialog")).toBeNull();

    // The editor stores what the section reports through its own draft reader.
    const { field, value } = onCreate.mock.calls[0][0];
    expect(field).toBe("output_contract");
    const { drafts, errors } = syncDraftsFromStep(step);
    const read = parseAdvancedJsonField(drafts, errors, field, value);
    expect(read.problem).toBeNull();
    cleanup();

    const onInsert = vi.fn();
    render(VariablePicker, {
      steps: [{ ...step, output_contract: read.problem === null ? read.parsed : null }],
      currentStepOrder: 2,
      formSchema: undefined,
      isAdvancedMode: true,
      onInsert
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
    );
    await fireEvent.click(await screen.findByRole("option", { name: /anomaly_days/ }));
    expect(onInsert).toHaveBeenCalledWith("{{step_1.output.structured.anomaly_days}}");
  });

  // Kills: an existing contract replaced without asking, and a confirmed
  // replacement that writes nothing.
  it("asks before it replaces a contract the step already has", async () => {
    const { onCreate, create } = await openWithExample(
      { type: "object", properties: { kept: { type: "string" } } },
      '{"total": 4}'
    );
    await fireEvent.click(create);
    const confirm = await screen.findByRole("alertdialog");
    expect(onCreate).not.toHaveBeenCalled();

    await fireEvent.click(
      within(confirm).getByRole("button", { name: m.flow_contract_example_replace() })
    );
    expect(onCreate).toHaveBeenCalledOnce();
    expect(JSON.parse(onCreate.mock.calls[0][0].value)).toMatchObject({
      properties: { total: { type: "number" } }
    });
  });

  // Kills: a key no variable path reaches shown as an ordinary field, or
  // refused although the contract may still hold it.
  it("marks a field whose name cannot be a variable, and still writes it", async () => {
    const { onCreate, dialog, create } = await openWithExample(null, '{"a.b": 1, "ok": 2}');
    const rows = within(dialog).getAllByRole("listitem");
    const badge = m.flow_contract_example_not_variable();
    expect(rows.map((row) => within(row).queryByText(badge) !== null)).toEqual([true, false]);
    expect(within(dialog).getByText(m.flow_contract_example_not_variable_reason())).toBeTruthy();
    await fireEvent.click(create);
    expect(JSON.parse(onCreate.mock.calls[0][0].value).required).toEqual(["a.b", "ok"]);
  });

  // Kills: a refused example that can still be written, and a refusal named
  // with another problem's sentence.
  it.each([
    ['{"id": 9007199254740993}', m.flow_contract_example_number_too_large],
    [
      JSON.stringify(
        Object.fromEntries(Array.from({ length: EXAMPLE_MAX_FIELDS + 1 }, (_, i) => [`f${i}`, 1]))
      ),
      () =>
        m.flow_contract_example_too_large({
          characters: String(EXAMPLE_MAX_CHARACTERS),
          fields: String(EXAMPLE_MAX_FIELDS)
        })
    ],
    ["{}", m.flow_contract_example_no_fields],
    ["[1]", m.flow_step_json_not_object],
    ["{oops", m.flow_step_json_parse_error]
  ])("refuses %s with its own sentence", async (example, sentence) => {
    const { onCreate, dialog, create } = await openWithExample(null, example);
    expect(within(dialog).getByRole("alert").textContent?.trim()).toBe(sentence());
    expect(create.hasAttribute("disabled")).toBe(true);
    await fireEvent.click(create);
    expect(onCreate).not.toHaveBeenCalled();
  });

  // Kills: the hint or the action shown on a step whose answer is not JSON or
  // whose mode the publish check refuses a contract for.
  it.each([
    ["json", { output_type: "json" }, true],
    ["text", { output_type: "text" }, false],
    ["speaker mapping", { output_type: "json", output_mode: "speaker_mapping" }, false]
  ] as const)("on a %s step, shows the hint and the action: %s", (_, overrides, shown) => {
    renderSection(flowStepFixture(overrides));
    expect(screen.queryByText(m.flow_step_output_contract_variables_hint()) !== null).toBe(shown);
    expect(screen.queryByRole("button", { name: m.flow_contract_example_button() }) !== null).toBe(
      shown
    );
  });

  // Kills: the action rendered in a different place once the editor opens, which
  // destroys the dialog it closes and drops the focus it returns.
  it("keeps the action and gives focus back to it after the contract is created", async () => {
    const { create } = await openWithExample(null, '{"total": 4}');
    const trigger = screen.getByRole("button", { name: m.flow_contract_example_button() });
    await fireEvent.click(create);
    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(screen.getByRole("button", { name: m.flow_contract_example_button() })).toBe(trigger);
    await vi.waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  // Kills: the picker offering a contract field no variable path reaches.
  it("does not offer a contract field whose name cannot be a variable", async () => {
    render(VariablePicker, {
      steps: [
        flowStepFixture({
          output_type: "json",
          output_contract: { type: "object", properties: { "a.b": {}, ok: {} } }
        })
      ],
      currentStepOrder: 2,
      formSchema: undefined,
      isAdvancedMode: true
    });
    await fireEvent.click(
      screen.getByRole("button", { name: /^(Infoga från flödet|Insert from the flow)$/ })
    );
    expect(await screen.findByRole("option", { name: /\bok\b/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /a\.b/ })).toBeNull();
  });
});
