// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { SettingsGroup, SettingsMarks, SettingsRow } from "./settings-rows";

afterEach(cleanup);

/** The header line that holds the title block and the header's actions. */
function headerLine(title: string) {
  return screen.getByRole("heading", { name: title }).parentElement!.parentElement!;
}

it("centres a lone title on its header action's line", () => {
  renderInApp(
    <SettingsGroup
      title="Instruktioner"
      headerEnd={<button type="button">Visa prompthistorik</button>}
    >
      <p>Prompt</p>
    </SettingsGroup>
  );
  expect(headerLine("Instruktioner").className).toContain("items-center");
  expect(headerLine("Instruktioner").className).not.toContain("items-start");
});

it("keeps the action at the top beside a title and a description", () => {
  renderInApp(
    <SettingsGroup
      title="API-nycklar"
      description="Nycklar som bara gäller den här resursen."
      headerEnd={<button type="button">Skapa nyckel</button>}
    >
      <p>Inga nycklar</p>
    </SettingsGroup>
  );
  expect(headerLine("API-nycklar").className).toContain("items-start");
});

/** The row a field is in: the settings row around its label. */
function rowOf(label: string) {
  return screen.getByText(label).closest<HTMLElement>("[class*='scroll-mt-32']")!;
}

function rows() {
  return (
    <>
      <SettingsRow title="Namn" htmlFor="name">
        <input id="name" />
      </SettingsRow>
      <SettingsRow title="Beskrivning" htmlFor="description">
        <input id="description" />
      </SettingsRow>
      <SettingsRow title="Modellinställningar" markKey="model-settings">
        <input aria-label="Nivå" />
      </SettingsRow>
    </>
  );
}

it("marks the rows it names with a label beside the title and a tint, the fields' names unchanged", () => {
  renderInApp(
    <SettingsMarks
      marks={{ rows: new Set(["name", "model-settings"]), label: "Ändrad från chatten" }}
    >
      {rows()}
    </SettingsMarks>
  );

  expect(screen.getAllByText("Ändrad från chatten")).toHaveLength(2);
  expect(within(rowOf("Namn")).getByText("Ändrad från chatten")).toBeTruthy();
  expect(rowOf("Namn").className).toContain("bg-ax-selected");
  expect(within(rowOf("Modellinställningar")).getByText("Ändrad från chatten")).toBeTruthy();
  expect(within(rowOf("Beskrivning")).queryByText("Ändrad från chatten")).toBeNull();
  expect(rowOf("Beskrivning").className).not.toContain("bg-ax-selected");
  // The label is beside the title, not part of the field's or the group's name.
  expect(screen.getByRole("textbox", { name: "Namn" })).toBeTruthy();
  expect(screen.getByRole("group", { name: "Modellinställningar" })).toBeTruthy();
});

it("marks nothing without marks, or outside them", () => {
  renderInApp(<SettingsMarks marks={null}>{rows()}</SettingsMarks>);
  expect(screen.queryByText("Ändrad från chatten")).toBeNull();
  cleanup();

  renderInApp(rows());
  expect(screen.queryByText("Ändrad från chatten")).toBeNull();
  expect(rowOf("Namn").className).toBe("flex scroll-mt-32 flex-col gap-2");
});
