// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowDefinition } from "./flow-definition";
import { flowFixture as flow, functionsFixture, namesFixture as names } from "./flow-fixtures";

afterEach(cleanup);

/** The card of a step: the Astryx clickable card's button names it, the list item holds its content. */
const cardOf = (name: string) => screen.getByRole("button", { name }).closest("li")!;

describe("FlowDefinition", () => {
  it("shows the oversight strip, every input and one card per step, the status being the header's", async () => {
    const onOpenStep = vi.fn();
    const { container } = renderInApp(
      <FlowDefinition flow={flow} names={names} onOpenStep={onOpenStep} canEdit />
    );

    expect(screen.queryByText("Publicerad v3")).toBeNull();
    expect(screen.queryByText("6 steg")).toBeNull();

    // Oversight: counts by kind and the gate sentence.
    const oversight = screen.getByRole("group", { name: "Steg per typ" });
    expect(within(oversight).getByText("1 modellsteg")).toBeTruthy();
    expect(within(oversight).getByText("1 granskning av en person")).toBeTruthy();
    expect(
      screen.getByText(
        "Ingen körning blir klar utan att en person har godkänt resultatet av steg 1. Steg 3–6 bygger på det godkända resultatet."
      )
    ).toBeTruthy();

    // Inputs with their type lines.
    const inputs = screen.getByRole("region", { name: "Indata vid körning" });
    expect(within(inputs).getByText("Inspelning")).toBeTruthy();
    expect(within(inputs).getByText("ljudfil · obligatorisk")).toBeTruthy();
    expect(within(inputs).getByText("text · valfri")).toBeTruthy();
    expect(within(inputs).getByText("Namn, kommaseparerade")).toBeTruthy();
    expect(within(inputs).getByText("val · obligatorisk · Nämnd, AU")).toBeTruthy();

    // One card per step, each opening the step by its key.
    const cards = screen.getAllByRole("button", { name: /^Öppna steg/ });
    expect(cards.map((card) => card.getAttribute("aria-label"))).toEqual([
      "Öppna steg 1: Transkribera mötet",
      "Öppna steg 2: Granska transkriptet",
      "Öppna steg 3: Sammanfatta beslut",
      "Öppna steg 4: Inledning",
      "Öppna steg 5: Skapa protokoll",
      "Öppna steg 6: Rita beslutsdiagram"
    ]);
    fireEvent.click(cards[2]!);
    expect(onOpenStep).toHaveBeenCalledWith("summary");

    // The view-mode note names Redigera; nothing here is editable.
    expect(screen.getByText(/Flödet visas i läsläge\. Välj Redigera/)).toBeTruthy();
    expect(container.querySelectorAll("input, textarea, select, [contenteditable]")).toHaveLength(
      0
    );
    await expectNoAxeViolations(container);
  });

  it("says what a model step reads and gives, coloured by source", () => {
    renderInApp(<FlowDefinition flow={flow} names={names} onOpenStep={() => {}} />);
    const card = cardOf("Öppna steg 3: Sammanfatta beslut");
    expect(within(card).getByText("Steg 2 · Granska transkriptet")).toBeTruthy();
    expect(within(card).getByText("Mötestyp")).toBeTruthy();
    expect(within(card).getByText("Inspelning")).toBeTruthy();
    expect(within(card).getByText("Delegationsordning")).toBeTruthy();
    expect(within(card).getByText("kommunen.se")).toBeTruthy();
    expect(within(card).getByText("Strukturerad data", { exact: false })).toBeTruthy();
    expect(within(card).getByText("decisions, actions, kind")).toBeTruthy();

    const document = cardOf("Öppna steg 5: Skapa protokoll");
    expect(within(document).getByText("Steg 4 · Inledning")).toBeTruthy();
    expect(within(document).getByText("Ifylld mall", { exact: false })).toBeTruthy();
    expect(within(document).getByText("Indata · Mötesdatum")).toBeTruthy();
  });

  it("shows a review step as a person's checkpoint with its time limit", () => {
    renderInApp(<FlowDefinition flow={flow} names={names} onOpenStep={() => {}} />);
    const card = cardOf("Öppna steg 2: Granska transkriptet");
    expect(within(card).getByText("Granskning")).toBeTruthy();
    expect(
      within(card).getByText(
        "Flödet pausar. En person redigerar och godkänner resultatet från steg 1 innan något mer körs."
      )
    ).toBeTruthy();
    expect(within(card).getByText("Tidsgräns 7 dagar")).toBeTruthy();
    expect(within(card).getByText("Avvisas: körningen stoppas")).toBeTruthy();
  });

  it("marks a function step the space cannot run", () => {
    const steps = flow.definition.steps!.map((step) =>
      step.key === "chart" ? { ...step, tool: "draw" } : step
    );
    renderInApp(
      <FlowDefinition
        flow={{ ...flow, definition: { ...flow.definition, steps } }}
        names={names}
        functions={functionsFixture}
        onOpenStep={() => {}}
      />
    );
    const card = cardOf("Öppna steg 6: Rita beslutsdiagram");
    expect(within(card).getByText("Kan inte köras")).toBeTruthy();
    expect(
      within(cardOf("Öppna steg 3: Sammanfatta beslut")).queryByText("Kan inte köras")
    ).toBeNull();
  });

  it("renders plain cards without an opener, as the history does", () => {
    renderInApp(<FlowDefinition flow={flow} names={names} />);
    expect(screen.queryAllByRole("button", { name: /^Öppna steg/ })).toHaveLength(0);
    expect(screen.getByRole("group", { name: "Steg 3: Sammanfatta beslut" })).toBeTruthy();
    expect(screen.queryByText(/Flödet visas i läsläge/)).toBeNull();
  });

  it("offers insertion points, moves and the inputs editor only in edit mode", async () => {
    const onInsertStep = vi.fn();
    const onMoveStep = vi.fn();
    const { rerender } = renderInApp(
      <FlowDefinition flow={flow} names={names} onOpenStep={() => {}} canEdit />
    );
    expect(screen.queryByRole("button", { name: /Infoga steg/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Åtgärder för/ })).toBeNull();

    rerender(
      <FlowDefinition
        flow={flow}
        names={names}
        onOpenStep={() => {}}
        canEdit
        mode="edit"
        onInsertStep={onInsertStep}
        onMoveStep={onMoveStep}
        onSaveInputs={() => Promise.resolve()}
      />
    );
    expect(screen.getAllByRole("button", { name: /^Infoga steg efter/ })).toHaveLength(5);
    expect(screen.getByRole("button", { name: "Lägg till steg sist" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Åtgärder för Inledning" }));
    // Every card's menu is in the document; the fourth card's is Inledning's.
    fireEvent.click(screen.getAllByRole("menuitem", { name: /Flytta upp/ })[3]!);
    expect(onMoveStep).toHaveBeenCalledWith("intro", -1);
    fireEvent.click(screen.getByRole("button", { name: "Redigera" }));
    expect(await screen.findByRole("dialog", { name: /Indata vid körning/ })).toBeTruthy();
  });

  it("says what is missing on an unpublished flow without inputs or steps", () => {
    renderInApp(
      <FlowDefinition
        flow={{
          ...flow,
          published_version: null,
          has_unpublished_changes: false,
          definition: { form_fields: [], steps: [] }
        }}
      />
    );
    expect(screen.getByText("Flödet tar inga indata vid körning.")).toBeTruthy();
    expect(screen.getByText("Flödet har inga steg ännu.")).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Steg per typ" })).toBeNull();
  });
});
