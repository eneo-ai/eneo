import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import FlowStructuredReviewEditor from "./FlowStructuredReviewEditor.svelte";
import { parseReviewValue } from "../structuredReview";

afterEach(cleanup);

describe("FlowStructuredReviewEditor", () => {
  it("edits typed fields without changing unknown data or choosing values for an empty row", async () => {
    const schema = {
      type: "array",
      minItems: 1,
      maxItems: 2,
      items: {
        type: "object",
        required: ["id", "name", "status", "quantity", "agreed"],
        properties: {
          id: { const: "contact", title: "Identifier" },
          name: { type: "string", title: "Namn" },
          status: { type: "string", enum: ["", "egen_uppgift"], title: "Status" },
          quantity: { type: "integer", title: "Antal" },
          agreed: { type: "boolean", title: "Bekräftat" }
        }
      }
    };
    const original = [
      {
        id: "contact",
        name: "Gunnar",
        status: "",
        quantity: 2,
        agreed: false,
        extra: { ref: "F001" }
      }
    ];
    const onChange = vi.fn();
    const props = { schema, text: JSON.stringify(original), disabled: false, onChange };
    const { rerender } = render(FlowStructuredReviewEditor, props);
    expect(
      screen
        .getByRole("button", { name: m.flow_run_review_remove_item({ number: 1 }) })
        .hasAttribute("disabled")
    ).toBe(true);
    expect((screen.getByLabelText("Status") as HTMLSelectElement).value).toBe('""');
    expect((screen.getByLabelText("Bekräftat") as HTMLSelectElement).value).toBe("false");
    expect(screen.queryByLabelText("Identifier")).toBeNull();

    await fireEvent.input(screen.getByLabelText("Namn"), { target: { value: "Ändrat namn" } });
    const renamed = [{ ...original[0], name: "Ändrat namn" }];
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual(renamed);
    await rerender({ ...props, text: JSON.stringify(renamed) });
    await fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: '"egen_uppgift"' }
    });
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual([
      { ...renamed[0], status: "egen_uppgift" }
    ]);
    await fireEvent.change(screen.getByLabelText("Bekräftat"), { target: { value: "true" } });
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual([{ ...renamed[0], agreed: true }]);
    await fireEvent.input(screen.getByLabelText("Antal"), { target: { value: "3" } });
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual([{ ...renamed[0], quantity: 3 }]);

    const addButton = screen.getByRole("button", { name: m.flow_run_review_add_item() });
    await fireEvent.click(addButton);
    const added = [...renamed, { id: "contact", name: "", status: "", quantity: "", agreed: "" }];
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual(added);
    await rerender({ ...props, text: JSON.stringify(added) });
    expect(addButton.hasAttribute("disabled")).toBe(true);
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_run_review_remove_item({ number: 1 }) })
    );
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual([added[1]]);
    await rerender({ ...props, text: onChange.mock.lastCall![0] });
    expect(addButton.hasAttribute("disabled")).toBe(false);
  });

  it("preserves unsupported contracts and incompatible stored values when editing a sibling", async () => {
    const original = {
      answer: "Before",
      union: { secret: "Retain" },
      mistyped: ["Still visible"],
      frozen: "Read only"
    };
    const onChange = vi.fn();
    render(FlowStructuredReviewEditor, {
      text: JSON.stringify(original),
      disabled: false,
      onChange,
      schema: {
        type: "object",
        properties: {
          answer: { type: "string" },
          union: { oneOf: [{ type: "string" }, { type: "object" }] },
          mistyped: { type: "string" },
          frozen: { type: "string", readOnly: true }
        }
      }
    });
    expect(screen.getByText(/Retain/)).toBeTruthy();
    expect(screen.getByText(/Still visible/)).toBeTruthy();
    expect(screen.getByText("Read only")).toBeTruthy();
    await fireEvent.input(screen.getByLabelText("Answer"), { target: { value: "After" } });
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual({ ...original, answer: "After" });
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_show_json() }));
    expect(
      (screen.getByLabelText(m.flow_run_review_json_payload()) as HTMLTextAreaElement).value
    ).toBe(JSON.stringify(original));
  });

  it("keeps malformed JSON repairable and shows fields after an advanced edit", async () => {
    const props = {
      text: "{bad",
      disabled: false,
      onChange: vi.fn(),
      schema: { type: "object", properties: { answer: { type: "string" } } }
    };
    const { rerender } = render(FlowStructuredReviewEditor, props);
    const raw = screen.getByLabelText(m.flow_run_review_json_payload());
    expect(raw.getAttribute("aria-invalid")).toBe("true");
    await fireEvent.input(raw, { target: { value: '{"answer":"Fixed"}' } });
    await rerender({ ...props, text: props.onChange.mock.lastCall![0] });
    expect((screen.getByLabelText("Answer") as HTMLTextAreaElement).value).toBe("Fixed");
  });

  it("disables field and advanced editing for a view-only result", async () => {
    render(FlowStructuredReviewEditor, {
      text: '{"answer":"Retained"}',
      disabled: true,
      onChange: vi.fn(),
      schema: { type: "object", properties: { answer: { type: "string" } } }
    });
    expect(screen.getByLabelText("Answer").hasAttribute("disabled")).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: m.flow_run_review_show_json() }));
    expect(screen.getByLabelText(m.flow_run_review_json_payload()).hasAttribute("disabled")).toBe(
      true
    );
  });
});
