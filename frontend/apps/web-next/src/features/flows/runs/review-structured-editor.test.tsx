// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { ReviewValue } from "./review-structured";
import { StructuredReviewEditor } from "./review-structured-editor";

const LONG_HELP =
  "Skriv beslutet så som det ska stå i protokollet, med paragraf, datum och vem som fattade det. " +
  "Använd hela meningar och inga förkortningar som läsaren inte känner till.";

const contract = {
  type: "object",
  properties: {
    beslut: { type: "string", title: "Beslut", description: LONG_HELP },
    ort: { type: "string", title: "Ort", description: "Var mötet hölls." },
    punkter: { type: "array", items: { type: "object", properties: { text: { type: "string" } } } }
  }
};

const original = { beslut: "Bifall", ort: "Sundsvall", punkter: [{ text: "a" }] };

function Editor({
  start,
  onChange
}: {
  start: ReviewValue;
  onChange?: (value: ReviewValue) => void;
}) {
  const [value, setValue] = useState<ReviewValue>(start);
  return (
    <StructuredReviewEditor
      id="editor"
      schema={contract}
      value={value}
      original={original}
      problem={null}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

afterEach(cleanup);

describe("StructuredReviewEditor", () => {
  it("marks the fields that differ from the step's output, with what they were", async () => {
    const { container } = renderInApp(
      <Editor start={{ beslut: "Avslag", ort: "Sundsvall", punkter: [{ text: "a" }] }} />
    );

    expect(screen.getAllByText(messages.flow_run_review_changed)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_previous_value }));
    expect(screen.getByText("Bifall")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("shows the step's own output read-only and goes back to the review", () => {
    renderInApp(<Editor start={{ beslut: "Avslag", ort: "Umeå", punkter: [] }} />);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_show_original }));
    expect(screen.getByText(messages.flow_run_review_original_help)).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: /Beslut/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_back_to_edit }));
    expect(screen.getByRole("textbox", { name: /Ort/ })).toBeTruthy();
  });

  it("edits the whole value as JSON, taking it only while it reads as JSON", () => {
    const changed = vi.fn();
    renderInApp(<Editor start={original} onChange={changed} />);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_show_json }));
    const json = screen.getByRole("textbox", { name: messages.flow_run_review_json_payload });
    fireEvent.change(json, { target: { value: '{"beslut": "Avslag"' } });
    expect(screen.getByText(messages.flow_run_review_payload_invalid)).toBeTruthy();
    expect(changed).not.toHaveBeenCalled();

    fireEvent.change(json, {
      target: { value: '{"beslut": "Avslag", "ort": "Sundsvall", "punkter": [{"text": "a"}]}' }
    });
    expect(changed).toHaveBeenLastCalledWith({
      beslut: "Avslag",
      ort: "Sundsvall",
      punkter: [{ text: "a" }]
    });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_show_fields }));
    expect((screen.getByRole("textbox", { name: /Beslut/ }) as HTMLTextAreaElement).value).toBe(
      "Avslag"
    );
  });

  it("puts a long description behind a help button and keeps a short one under its field", () => {
    renderInApp(<Editor start={original} />);

    expect(screen.getByText("Var mötet hölls.")).toBeTruthy();
    expect(screen.queryByText(LONG_HELP)).toBeNull();
    const help = screen.getByRole("button", {
      name: messages.flow_run_review_field_help.replace("{label}", "Beslut")
    });
    expect(help.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(help);
    expect(screen.getByText(LONG_HELP)).toBeTruthy();
    expect(help.getAttribute("aria-expanded")).toBe("true");
  });
});
