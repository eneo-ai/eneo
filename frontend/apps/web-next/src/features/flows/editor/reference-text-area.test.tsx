// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { makeFlow, makeStep } from "../flow-fixtures";
import { TemplateScope, TemplateTextArea } from "./reference-text-area";
import { variableGroups } from "./step-variables";

const state = vi.hoisted(() => ({ announce: vi.fn() }));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const flow = makeFlow({
  steps: [
    makeStep(1, { user_description: "Sammanfatta" }),
    makeStep(2, { user_description: "Svara" })
  ]
});

function Field({ initial, perSection = false }: { initial: string; perSection?: boolean }) {
  const [value, setValue] = useState(initial);
  return (
    <TemplateScope value={{ flow, stepOrder: 2 }}>
      <TemplateTextArea
        label="Instruktion"
        value={value}
        onChange={setValue}
        groups={variableGroups({ flow, stepOrder: 2, sectionVariables: perSection })}
      />
    </TemplateScope>
  );
}

/** Types `value` into the field as its whole text, with the caret after it. */
function type(area: HTMLTextAreaElement, value: string, inputType = "insertText") {
  area.focus();
  fireEvent.input(area, { target: { value }, inputType });
}

describe("TemplateTextArea", () => {
  it("lists the references to complete after {{ and writes the chosen one", async () => {
    renderInApp(<Field initial="" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    expect(area.getAttribute("aria-autocomplete")).toBe("list");

    type(area, "Läs {{samman");
    const list = screen.getByRole("listbox", { name: "Hänvisningar" });
    expect(area.getAttribute("aria-controls")).toBe(list.id);
    const options = within(list).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "Steg 1: Sammanfatta: Svaret som text{{step_1.output.text}}"
    ]);
    expect(area.getAttribute("aria-activedescendant")).toBe(options[0]!.id);
    expect(options[0]!.getAttribute("aria-selected")).toBe("true");
    expect(state.announce).toHaveBeenCalledWith("1 förslag. Välj med pil upp och ned och Enter.");
    await expectNoAxeViolations(document.body);

    fireEvent.keyDown(area, { key: "Enter" });
    expect(area.value).toBe("Läs {{step_1.output.text}}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(document.activeElement).toBe(area);
    expect(area.selectionStart).toBe(area.value.length);
  });

  it("moves through the suggestions with the arrows and closes on Escape", () => {
    renderInApp(<Field initial="" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    type(area, "Hej @");
    const options = within(screen.getByRole("listbox")).getAllByRole("option");
    expect(options.length).toBeGreaterThan(2);

    fireEvent.keyDown(area, { key: "ArrowDown" });
    expect(area.getAttribute("aria-activedescendant")).toBe(options[1]!.id);
    fireEvent.keyDown(area, { key: "ArrowUp" });
    fireEvent.keyDown(area, { key: "ArrowUp" });
    expect(area.getAttribute("aria-activedescendant")).toBe(options.at(-1)!.id);
    // The count is announced once when the list opens, not again as the highlight moves.
    expect(state.announce).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(area, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(area.getAttribute("aria-activedescendant")).toBeNull();
    // Moving the caret does not bring back what Escape closed.
    fireEvent.click(area);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("chooses a suggestion with a click and keeps the caret in the text", () => {
    renderInApp(<Field initial="" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    type(area, "Skriv @dat");
    const option = screen.getByRole("option", { name: /Dagens datum/ });
    expect(fireEvent.mouseDown(option)).toBe(false);
    fireEvent.click(option);
    expect(area.value).toBe("Skriv {{datum}}");
  });

  it("names what each reference reads as a chip, a removed step in red", async () => {
    const { container } = renderInApp(
      <Field initial="Läs {{step_1.output.text}} och {{ step_3_deleted.output.text }}" />
    );
    const reads = screen.getByRole("list", { name: "Texten läser" });
    expect(
      within(reads)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual([
      expect.stringContaining("Steg 1: Sammanfatta › text"),
      expect.stringContaining("Steg 3 finns inte")
    ]);
    await expectNoAxeViolations(container);
  });

  it("warns at the field about fields of a step that answers in text", () => {
    renderInApp(<Field initial="Beslut: {{step_1.output.structured.beslut}}" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" });
    const warning = messages.flow_step_editor_reference_warning_fields_of_text.replace(
      "{step}",
      "Steg 1: Sammanfatta"
    );

    expect(screen.getByText(warning)).toBeTruthy();
    expect(area.getAttribute("aria-describedby")).toContain(
      screen.getByText(warning).closest("[id]")?.id
    );
    const reads = screen.getByRole("list", { name: "Texten läser" });
    expect(within(reads).getByRole("listitem").textContent).toContain(
      "Steg 1: Sammanfatta › fält, men steget svarar inte i fast format"
    );
  });

  it("warns about the section's number only outside an instruction run per section", () => {
    renderInApp(<Field initial="Del {{section_index}}" />);
    expect(
      screen.getByText(messages.flow_step_editor_reference_warning_section_index)
    ).toBeTruthy();
    cleanup();
    renderInApp(<Field initial="Del {{section_index}}" perSection />);
    expect(
      screen.queryByText(messages.flow_step_editor_reference_warning_section_index)
    ).toBeNull();
    expect(screen.getByRole("list", { name: "Texten läser" }).textContent).toContain(
      messages.flow_step_editor_variable_section_index
    );
  });

  it("opens nothing for an @ inside a word or after deleting", () => {
    renderInApp(<Field initial="" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    type(area, "anna@kommun");
    expect(screen.queryByRole("listbox")).toBeNull();
    type(area, "Läs {{", "deleteContentBackward");
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});
