// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { makeFlow, makeStep } from "../flow-fixtures";
import { TemplateScope } from "./editor-fields";
import { TemplateTextArea } from "./reference-text-area";
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
      expect.stringContaining("Ett borttaget steg")
    ]);
    await expectNoAxeViolations(container);
  });

  it("says in words what an unknown name and a step that comes later read", () => {
    renderInApp(<Field initial="Skriv {{datun}} och {{step_2.output.text}}" />);
    const reads = screen.getByRole("list", { name: "Texten läser" });
    expect(
      within(reads)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual([expect.stringContaining("Okänd: datun"), expect.stringContaining("Det här steget")]);
    expect(
      screen.getByText(
        "Hittar ingen variabel som heter datun. Välj en i Infoga variabel. " +
          "Ett steg kan bara läsa tidigare steg."
      )
    ).toBeTruthy();
  });

  it("warns about a reference that is opened and never closed", () => {
    renderInApp(<Field initial="Läs {{transkribering} och svara" />);
    expect(
      screen.getByText(
        "{{transkribering} saknar }} och skickas som vanlig text. Avsluta med }}, eller välj en i Infoga variabel."
      )
    ).toBeTruthy();
  });

  it("waits with the unclosed warning until the text moves past the reference or is left", () => {
    renderInApp(<Field initial="" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    const unclosed = /saknar \}\} och skickas som vanlig text/;
    // Not on each keystroke of the reference being typed.
    for (const typed of ["Läs {{", "Läs {{d", "Läs {{dat"]) {
      type(area, typed);
      expect(screen.queryByText(unclosed)).toBeNull();
    }
    type(area, "Läs {{dat och");
    expect(screen.getByText(unclosed).textContent).toMatch(/^\{\{dat saknar/);
    type(area, "Läs {{dat");
    expect(screen.queryByText(unclosed)).toBeNull();
    fireEvent.blur(area);
    expect(screen.getByText(unclosed).textContent).toMatch(/^\{\{dat saknar/);
  });

  it("keeps warning about an earlier unclosed reference while a new one is typed", () => {
    renderInApp(<Field initial="" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    type(area, "Läs {{transkribering} och {{d");
    expect(screen.getByText(/saknar \}\} och skickas som vanlig text/).textContent).toMatch(
      /^\{\{transkribering\} saknar/
    );
  });

  it("inserts from the menu at the end of a text never focused, apart from the word before", async () => {
    renderInApp(<Field initial="Sammanfatta" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    area.setSelectionRange(0, 0);
    fireEvent.click(screen.getByRole("button", { name: "Infoga variabel" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Dagens datum/ }));
    await vi.waitFor(() => expect(area.value).toBe("Sammanfatta {{datum}}"));
  });

  it("inserts from the menu where the caret was when the text lost focus", async () => {
    renderInApp(<Field initial="Läs noga" />);
    const area = screen.getByRole("textbox", { name: "Instruktion" }) as HTMLTextAreaElement;
    area.focus();
    area.setSelectionRange(3, 3);
    fireEvent.blur(area);
    area.setSelectionRange(0, 0);
    fireEvent.click(screen.getByRole("button", { name: "Infoga variabel" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Dagens datum/ }));
    await vi.waitFor(() => expect(area.value).toBe("Läs {{datum}} noga"));
  });

  it("tells where form fields come from when the flow has none, as text and not a row", async () => {
    renderInApp(<Field initial="" />);
    fireEvent.click(screen.getByRole("button", { name: "Infoga variabel" }));
    const menu = await screen.findByRole("dialog", { name: "Infoga variabel" });
    expect(within(menu).getByText(messages.flow_step_editor_variables_no_fields)).toBeTruthy();
    // Every row can be reached with the arrows: none is a disabled stand-in.
    const rows = within(menu).getAllByRole("menuitem");
    expect(rows.every((row) => row.getAttribute("aria-disabled") !== "true")).toBe(true);
    expect(rows.map((row) => row.textContent).join(" ")).not.toContain("formulärfält");
    await expectNoAxeViolations(document.body);
  });

  it("says nothing about missing form fields when the flow has fields it cannot read", async () => {
    const withField = makeFlow({
      ...flow,
      metadata_json: { form_schema: { fields: [{ name: "text", label: "Text", type: "text" }] } }
    });
    renderInApp(
      <TemplateScope value={{ flow: withField, stepOrder: 2 }}>
        <TemplateTextArea
          label="Instruktion"
          value=""
          onChange={() => {}}
          groups={variableGroups({ flow: withField, stepOrder: 2 })}
        />
      </TemplateScope>
    );
    fireEvent.click(screen.getByRole("button", { name: "Infoga variabel" }));
    await screen.findAllByRole("menuitem");
    expect(screen.queryByText(messages.flow_step_editor_variables_no_fields)).toBeNull();
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
