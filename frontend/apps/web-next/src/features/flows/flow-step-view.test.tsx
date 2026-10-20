// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { flowFixture as flow, functionsFixture, namesFixture as names } from "./flow-fixtures";
import { FlowStepView } from "./flow-step-view";

afterEach(cleanup);

function view(stepKey: string, wide = true, definition = flow.definition) {
  const onSelectStep = vi.fn();
  const onClose = vi.fn();
  const onEdit = vi.fn();
  const utils = renderInApp(
    <FlowStepView
      definition={definition}
      stepKey={stepKey}
      names={names}
      functions={functionsFixture}
      wide={wide}
      onClose={onClose}
      onSelectStep={onSelectStep}
      onEdit={onEdit}
    />
  );
  return { ...utils, onSelectStep, onClose, onEdit };
}

describe("FlowStepView", () => {
  it("shows a model step's sections in execution order, with the navigator when wide", async () => {
    const { container, onSelectStep, onClose, onEdit } = view("summary");
    expect(screen.getByText("Steg 3 av 6")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Sammanfatta beslut" })).toBeTruthy();
    expect(screen.getByText("Plockar ut besluten ur det granskade transkriptet.")).toBeTruthy();

    const headings = screen
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(headings.slice(0, 2)).toEqual(["Steg", "Indata vid körning"]);
    expect(headings.slice(2)).toEqual([
      "Läser",
      "Modell",
      "Instruktion till modellen",
      "Producerar",
      "Resultatet används av"
    ]);

    // Läser: the review's result, the input, the attached file, the knowledge.
    const reads = screen.getByRole("region", { name: "Läser" });
    // Named as a row and again inside the input template behind the disclosure.
    expect(within(reads).getAllByText("Steg 2 · Granska transkriptet").length).toBe(2);
    expect(within(reads).getByText("Granskat resultat")).toBeTruthy();
    expect(within(reads).getByText("Mötestyp")).toBeTruthy();
    expect(within(reads).getByText("Fil · bifogas")).toBeTruthy();
    expect(within(reads).getByText("Delegationsordning")).toBeTruthy();
    expect(within(reads).getByText("Visa hur indata sätts ihop till modellen")).toBeTruthy();

    // Modell with its settings; the prompt as prose.
    const model = screen.getByRole("region", { name: "Modell" });
    expect(within(model).getByText("GPT-5.2")).toBeTruthy();
    expect(within(model).getByText("temperature")).toBeTruthy();
    expect(screen.getByText("Lista varje beslut med kort motivering.")).toBeTruthy();

    // Producerar: the schema as a field table, the raw schema behind a disclosure.
    const produces = screen.getByRole("region", { name: "Producerar" });
    expect(within(produces).getByText("Strukturerad data med 3 fält")).toBeTruthy();
    expect(within(produces).getByText("1 av 3 måste finnas")).toBeTruthy();
    expect(within(produces).getByText("decisions")).toBeTruthy();
    expect(within(produces).getAllByText("Lista med text").length).toBe(2);
    expect(within(produces).getByText("Ett av Nämnd, AU")).toBeTruthy();
    expect(within(produces).getByText("Visa JSON-schemat")).toBeTruthy();

    // Används av: the later steps that read this one, each opening that step.
    const usedBy = screen.getByRole("region", { name: "Resultatet används av" });
    expect(within(usedBy).getByText("Steg 4 · Inledning")).toBeTruthy();
    expect(within(usedBy).getByText("Steg 6 · Rita beslutsdiagram")).toBeTruthy();
    fireEvent.click(within(usedBy).getByText("Steg 6 · Rita beslutsdiagram"));
    expect(onSelectStep).toHaveBeenCalledWith("chart");

    // The navigator: back to the overview, every step, the inputs.
    const nav = screen.getByRole("navigation", { name: "Steg i flödet" });
    fireEvent.click(within(nav).getAllByRole("button", { name: "Översikt" })[0]!);
    expect(onClose).toHaveBeenCalled();
    fireEvent.click(
      within(nav).getAllByRole("button", { name: "Öppna steg 5: Skapa protokoll" })[0]!
    );
    expect(onSelectStep).toHaveBeenCalledWith("minutes");

    fireEvent.click(screen.getByRole("button", { name: "Redigera flödet" }));
    expect(onEdit).toHaveBeenCalled();

    expect(screen.getByText("summary")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("shows a review step as a sequence with its target, mode and time limit", () => {
    const { onSelectStep } = view("check");
    expect(
      screen.getByText("Körningen stannar och granskaren får resultatet från steg 1 att läsa.")
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Vid godkännande fortsätter steg 3 med den godkända versionen. Vid avvisning stoppas körningen och motiveringen sparas."
      )
    ).toBeTruthy();
    const reviews = screen.getByRole("region", { name: "Granskar resultatet av" });
    fireEvent.click(within(reviews).getByText("Steg 1 · Transkribera mötet"));
    expect(onSelectStep).toHaveBeenCalledWith("transcript");
    expect(screen.getByText("Redigera och godkänna")).toBeTruthy();
    expect(screen.getByText("Högst 7 dagar, sedan avbryts körningen")).toBeTruthy();
    const usedBy = screen.getByRole("region", { name: "Resultatet används av" });
    expect(within(usedBy).getByText("Steg 3 · Sammanfatta beslut")).toBeTruthy();
  });

  it("shows a document step's template, bindings and file", () => {
    view("minutes");
    const document = screen.getByRole("region", { name: "Dokument" });
    expect(within(document).getByText("Protokollmall.docx")).toBeTruthy();
    expect(within(document).getByText("meeting_date")).toBeTruthy();
    expect(within(document).getByText("Föregående steg")).toBeTruthy();
    const produces = screen.getByRole("region", { name: "Producerar" });
    expect(within(produces).getByText("Ifylld mall")).toBeTruthy();
    expect(within(produces).getByText("protokoll-", { exact: false })).toBeTruthy();
  });

  it("shows a transcription's source, model, language and speakers", () => {
    view("transcript");
    const section = screen.getByRole("region", { name: "Transkribering" });
    expect(within(section).getByText("Inspelning")).toBeTruthy();
    expect(within(section).getByText("KB-Whisper large")).toBeTruthy();
    expect(within(section).getByText("sv")).toBeTruthy();
    expect(
      within(section).getByText("Identifiera talare, högst 6 · namnge från Deltagare")
    ).toBeTruthy();
    const usedBy = screen.getByRole("region", { name: "Resultatet används av" });
    expect(within(usedBy).getByText("Granskar resultatet")).toBeTruthy();
  });

  it("shows a function step's tool, provider and arguments as templates", () => {
    view("chart");
    const section = screen.getByRole("region", { name: "Funktion" });
    expect(within(section).getByText("render_chart")).toBeTruthy();
    expect(within(section).getByText("Diagramtjänsten")).toBeTruthy();
    expect(within(section).queryByText(/Steget kan inte köras/)).toBeNull();
    expect(within(section).getByText("Steg 3 · Sammanfatta beslut · decisions")).toBeTruthy();
    expect(within(section).getByText("bar")).toBeTruthy();
    expect(screen.getByText("Inget senare steg läser detta resultat direkt.")).toBeTruthy();
  });

  it("warns when a function step's purpose is not enabled in the space", () => {
    const steps = flow.definition.steps!.map((step) =>
      step.key === "chart" ? { ...step, purpose: "web_search" as const, tool: "search" } : step
    );
    view("chart", true, { ...flow.definition, steps });
    expect(screen.getByText("Steget kan inte köras som det är")).toBeTruthy();
    expect(
      screen.getByText(
        "Funktionen är inte aktiverad i rummet. Aktivera den i rummets inställningar, eller välj en annan funktion."
      )
    ).toBeTruthy();
  });

  it("is one column under a pager when the panel is narrow", () => {
    const { onSelectStep, onClose } = view("intro", false);
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.getAllByText("Steg 4 av 6").length).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "Nästa steg" }));
    expect(onSelectStep).toHaveBeenCalledWith("minutes");
    fireEvent.click(screen.getByRole("button", { name: "Föregående steg" }));
    expect(onSelectStep).toHaveBeenCalledWith("summary");
    fireEvent.click(screen.getByRole("button", { name: "Översikt" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("offers the way back when the step is gone", () => {
    view("missing");
    expect(screen.getByText("Steget finns inte längre i flödet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Översikt" })).toBeTruthy();
  });
});
