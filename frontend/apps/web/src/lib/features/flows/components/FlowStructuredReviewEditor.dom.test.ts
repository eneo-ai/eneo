import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import FlowStructuredReviewEditor from "./FlowStructuredReviewEditor.svelte";
import { parseReviewValue } from "../structuredReview";

// The select primitive needs pointer capture and scrolling, which jsdom omits.
Element.prototype.animate ??= (() => ({
  cancel() {},
  finished: Promise.resolve(),
  onfinish: null
})) as never;
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => undefined;
Element.prototype.releasePointerCapture ??= () => undefined;
Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });

afterEach(cleanup);

describe("FlowStructuredReviewEditor", () => {
  it("shows list counts, collapses empty sections and reaches a fact without redundant headings", async () => {
    render(FlowStructuredReviewEditor, {
      text: JSON.stringify({
        section: { heading: "Anteckningar", entries: [{ statement: "Kontrollera uppgiften" }] },
        empty: []
      }),
      schema: {
        type: "object",
        properties: {
          section: {
            type: "object",
            title: "Anteckningar",
            properties: {
              heading: { const: "Anteckningar" },
              entries: {
                type: "array",
                title: "Uppgifter",
                items: {
                  type: "object",
                  properties: {
                    statement: {
                      type: "string",
                      title: "Uppgift",
                      description: "Behåll villkoren i underlaget."
                    }
                  }
                }
              }
            }
          },
          empty: { type: "array", title: "Kompletteringar", items: { type: "string" } }
        }
      },
      disabled: false,
      onChange: vi.fn()
    });
    const section = screen.getByText("Anteckningar").closest("details");
    if (!section) throw new Error("Missing section disclosure");
    expect(section.open).toBe(false);
    expect(
      screen.getByText(m.flow_run_review_collection_count({ label: "Uppgifter", count: 1 }))
    ).toBeTruthy();
    expect(screen.getByText("Kompletteringar").closest("details")?.open).toBe(false);
    section.open = true;
    await fireEvent(section, new Event("toggle"));
    const row = screen.getByText("Kontrollera uppgiften").closest("details");
    if (!row) throw new Error("Missing fact disclosure");
    row.open = true;
    await fireEvent(row, new Event("toggle"));
    expect(screen.getByLabelText("Uppgift")).toBeTruthy();
    expect(screen.queryByText("Behåll villkoren i underlaget.")).toBeNull();
    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_run_review_field_help({ label: "Uppgift" }) })
    );
    expect(screen.getByText("Behåll villkoren i underlaget.")).toBeTruthy();
  });

  it("keeps a section's extra fields visible without repeating its heading inside it", async () => {
    render(FlowStructuredReviewEditor, {
      text: JSON.stringify({
        section: { heading: "Anteckningar", entries: [], qualification: "Endast vid behov" }
      }),
      schema: {
        type: "object",
        properties: {
          section: {
            title: "Anteckningar",
            type: "object",
            properties: {
              heading: { const: "Anteckningar", title: "Rubrik" },
              entries: { type: "array", title: "Uppgifter", items: { type: "string" } }
            }
          }
        }
      },
      disabled: false,
      onChange: vi.fn()
    });
    const section = screen.getByText("Anteckningar").closest("details");
    if (!section) throw new Error("Missing section disclosure");
    section.open = true;
    await fireEvent(section, new Event("toggle"));
    expect(screen.queryByText("Rubrik")).toBeNull();
    expect(screen.getByText("Qualification")).toBeTruthy();
    expect(screen.getByText("Endast vid behov")).toBeTruthy();
    expect(screen.getByText("Uppgifter").closest("details")?.open).toBe(false);
  });

  it("compares an edited list with its complete original without pairing different items", async () => {
    const schema = {
      type: "object",
      properties: {
        notes: { title: "Anteckningar", type: "array", items: { type: "string" } }
      }
    };
    const onChange = vi.fn();
    render(FlowStructuredReviewEditor, {
      schema,
      text: '{"notes":["Två","Ny"]}',
      originalText: '{"notes":["Ett","Två"]}',
      disabled: false,
      onChange
    });
    expect(screen.getAllByText(m.flow_run_review_changed())).toHaveLength(1);
    const comparison = screen.getByText(m.flow_run_review_previous_value()).closest("details");
    if (!comparison) throw new Error("Missing original list");
    expect(screen.queryByText("Ett")).toBeNull();
    comparison.open = true;
    await fireEvent(comparison, new Event("toggle"));
    expect(screen.getByText("Ett")).toBeTruthy();
    expect(screen.getByText("Två")).toBeTruthy();
    expect(comparison.querySelector("textarea, input, select")).toBeNull();
    await fireEvent.input(screen.getByLabelText(m.flow_run_review_item({ number: 2 })), {
      target: { value: "Ny rättelse" }
    });
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual({ notes: ["Två", "Ny rättelse"] });
  });

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
    const press = async (element: HTMLElement) => {
      await fireEvent.pointerDown(element, { pointerType: "mouse", button: 0 });
      await fireEvent.pointerUp(element, { pointerType: "mouse", button: 0 });
      await fireEvent.click(element);
    };
    const choose = async (field: string, option: string) => {
      await press(screen.getByRole("button", { name: field }));
      await press(screen.getByRole("option", { name: option }));
    };
    // A row is summarised by its own content, so it is reached through its
    // remove control rather than through a positional label.
    const openRow = async () => {
      const row = screen
        .getByRole("button", { name: m.flow_run_review_remove_item({ number: 1 }) })
        .closest("[data-review-item]")
        ?.querySelector("details");
      if (!row) throw new Error("Missing row disclosure");
      if (row.open) return;
      row.open = true;
      await fireEvent(row, new Event("toggle"));
    };
    await openRow();
    // The contract offers the empty string as a choice, so it reads as chosen.
    expect(screen.getByRole("button", { name: "Status" }).textContent?.trim()).toBe(
      m.flow_run_review_empty_value()
    );
    expect(screen.getByRole("button", { name: "Bekräftat" }).textContent?.trim()).toBe(m.no());
    expect(screen.queryByLabelText("Identifier")).toBeNull();

    await fireEvent.input(screen.getByLabelText("Namn"), { target: { value: "Ändrat namn" } });
    const renamed = [{ ...original[0], name: "Ändrat namn" }];
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual(renamed);
    await rerender({ ...props, text: JSON.stringify(renamed) });
    await openRow();
    await choose("Status", "Egen uppgift");
    expect(parseReviewValue(onChange.mock.lastCall![0])).toEqual([
      { ...renamed[0], status: "egen_uppgift" }
    ]);
    await choose("Bekräftat", m.yes());
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
