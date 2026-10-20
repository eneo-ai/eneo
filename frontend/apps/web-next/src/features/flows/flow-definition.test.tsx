// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowDefinition } from "./flow-definition";
import { FlowStepCard } from "./flow-step-card";
import type { FlowPublic } from "./types";

/** One flow with every step kind, every parameter set. */
const flow: FlowPublic = {
  id: "flow-1",
  space_id: "space-1",
  name: "Mötesprotokoll",
  description:
    "Transkriberar en mötesinspelning, pausar för granskning och fyller protokollmallen.",
  published_version: 3,
  has_unpublished_changes: true,
  conversation_id: "session-1",
  created_at: "2026-10-20T08:00:00Z",
  updated_at: "2026-10-20T09:00:00Z",
  definition: {
    schema_version: 1,
    form_fields: [
      { key: "recording", label: "Inspelning", type: "audio", required: true },
      { key: "meeting_date", label: "Mötesdatum", type: "text", required: true },
      {
        key: "participants",
        label: "Deltagare",
        type: "text",
        required: false,
        description: "Namn, kommaseparerade"
      },
      { key: "kind", label: "Mötestyp", type: "select", required: true, options: ["Nämnd", "AU"] }
    ],
    steps: [
      {
        kind: "transcribe",
        key: "transcript",
        id: "s1",
        name: "Transkribera mötet",
        source: "recording",
        transcription_model_id: "tm-1",
        language: "sv",
        speaker_labels: true,
        max_speakers: 6,
        speaker_mapping: { participants_field: "participants", infer_names: true }
      },
      {
        kind: "review",
        key: "check",
        id: "s2",
        name: "Granska transkriptet",
        mode: "edit",
        of: "transcript",
        expires_after_seconds: 7 * 86_400
      },
      {
        kind: "llm",
        key: "summary",
        id: "s3",
        name: "Sammanfatta beslut",
        prompt: "Lista varje beslut med kort motivering.",
        input: "{{steps.check}}\n\nMötestyp: {{form.kind}}",
        model_id: "model-1",
        model_kwargs: { temperature: 0 },
        files_from: ["recording"],
        knowledge: { collection_ids: ["collection-1"], website_ids: ["website-1"] },
        output: {
          type: "json",
          schema: {
            type: "object",
            properties: { decisions: { type: "array" }, actions: { type: "array" } }
          }
        }
      },
      {
        kind: "compose",
        key: "intro",
        id: "s4",
        name: "Inledning",
        template: "Protokoll fört {{form.meeting_date}}. Beslut: {{steps.summary.json.decisions}}"
      },
      {
        kind: "document",
        key: "minutes",
        id: "s5",
        name: "Skapa protokoll",
        format: "pdf",
        template_file_id: "file-1",
        title: "Protokoll {{form.meeting_date}}",
        filename: "protokoll-{{form.meeting_date}}",
        values: { meeting_date: "{{form.meeting_date}}", decisions: "{{previous}}" }
      }
    ]
  }
};

const names = {
  modelName: (id: string) => (id === "model-1" ? "GPT-5.2" : null),
  transcriptionModelName: (id: string) => (id === "tm-1" ? "KB-Whisper large" : null),
  collectionName: (id: string) => (id === "collection-1" ? "Delegationsordning" : null),
  websiteName: (id: string) => (id === "website-1" ? "kommunen.se" : null),
  fileName: (id: string) => (id === "file-1" ? "Protokollmall.docx" : null)
};

const steps = flow.definition.steps!;

afterEach(cleanup);

describe("FlowDefinition", () => {
  it("shows the status, every input and one row per step, and opens a step in a dialog", async () => {
    const { container } = renderInApp(<FlowDefinition flow={flow} names={names} />);

    // Status and inputs.
    expect(screen.getByText("Publicerad v3")).toBeTruthy();
    expect(screen.getByText("Opublicerade ändringar")).toBeTruthy();
    expect(screen.getByText("5 steg")).toBeTruthy();
    const inputs = screen.getByRole("region", { name: "Indata vid körning" });
    expect(within(inputs).getByText("Inspelning")).toBeTruthy();
    expect(within(inputs).getByText("ljudfil · obligatorisk")).toBeTruthy();
    expect(within(inputs).getByText("text · valfri")).toBeTruthy();
    expect(within(inputs).getByText("Namn, kommaseparerade")).toBeTruthy();
    expect(within(inputs).getByText("val · obligatorisk · Nämnd, AU")).toBeTruthy();

    // One collapsed row per step: number, name, a one-line summary and the kind.
    const rows = screen.getAllByRole("button", { name: /^Visa inställningar för steg/ });
    expect(rows.map((row) => row.getAttribute("aria-label"))).toEqual([
      "Visa inställningar för steg 1: Transkribera mötet",
      "Visa inställningar för steg 2: Granska transkriptet",
      "Visa inställningar för steg 3: Sammanfatta beslut",
      "Visa inställningar för steg 4: Inledning",
      "Visa inställningar för steg 5: Skapa protokoll"
    ]);
    expect(within(rows[0]!).getByText("KB-Whisper large")).toBeTruthy();
    expect(within(rows[1]!).getByText("Redigering och godkännande")).toBeTruthy();
    expect(within(rows[2]!).getByText("GPT-5.2 · JSON-utdata")).toBeTruthy();
    expect(within(rows[4]!).getByText("PDF · Protokollmall.docx")).toBeTruthy();

    // Nothing is editable: the rows are the only buttons, there are no fields.
    expect(container.querySelectorAll("input, textarea, select, [contenteditable]")).toHaveLength(
      0
    );
    await expectNoAxeViolations(container);

    // A row opens the step with every parameter in a dialog.
    fireEvent.click(rows[2]!);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Sammanfatta beslut")).toBeTruthy();
    expect(within(dialog).getByText("Steg 3 av 5 · Modell")).toBeTruthy();
    expect(within(dialog).getByText("Lista varje beslut med kort motivering.")).toBeTruthy();
    expect(within(dialog).getByText("GPT-5.2")).toBeTruthy();
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
    expect(screen.getByText("Utkast")).toBeTruthy();
    expect(screen.getByText("Flödet tar inga indata vid körning.")).toBeTruthy();
    expect(screen.getByText("Flödet har inga steg ännu.")).toBeTruthy();
  });
});

describe("FlowStepCard", () => {
  const card = (index: number) => {
    const { container } = renderInApp(
      <FlowStepCard step={steps[index]!} index={index} definition={flow.definition} names={names} />
    );
    return { container, article: screen.getByRole("article") };
  };

  it("shows a transcribe step's source, model, language and speakers", () => {
    const { article } = card(0);
    expect(within(article).getByText("Transkribering")).toBeTruthy();
    expect(within(article).getByText("Indata · Inspelning")).toBeTruthy();
    expect(within(article).getByText("KB-Whisper large")).toBeTruthy();
    expect(within(article).getByText("sv")).toBeTruthy();
    expect(
      within(article).getByText("Identifiera talare, högst 6 · namnge från Deltagare")
    ).toBeTruthy();
  });

  it("shows a review step's mode, target and time limit", () => {
    const { article } = card(1);
    expect(within(article).getByText("Granskning")).toBeTruthy();
    expect(
      within(article).getByText("Redigera: granskaren kan ändra texten innan den godkänns")
    ).toBeTruthy();
    expect(within(article).getByText("Steg 1 · Transkribera mötet")).toBeTruthy();
    expect(within(article).getByText("Högst 7 dagar, sedan avbryts körningen")).toBeTruthy();
  });

  it("shows an llm step's prompt, input references, model, knowledge, files and JSON output", () => {
    const { article } = card(2);
    expect(within(article).getByText("Lista varje beslut med kort motivering.")).toBeTruthy();
    expect(within(article).getByText("Steg 2 · Granska transkriptet")).toBeTruthy();
    expect(within(article).getByText("Indata · Mötestyp")).toBeTruthy();
    expect(within(article).getByText("GPT-5.2")).toBeTruthy();
    expect(within(article).getByText("· temperature: 0")).toBeTruthy();
    expect(within(article).getByText("Delegationsordning")).toBeTruthy();
    expect(within(article).getByText("kommunen.se")).toBeTruthy();
    expect(within(article).getByText("Indata · Inspelning")).toBeTruthy();
    expect(within(article).getByText("JSON enligt schema", { exact: false })).toBeTruthy();
    expect(within(article).getByText("decisions, actions")).toBeTruthy();
    expect(within(article).getByText(/"type": "object"/)).toBeTruthy();
  });

  it("shows a compose step's template with its references", () => {
    const { article } = card(3);
    expect(within(article).getByText("Protokoll fört", { exact: false })).toBeTruthy();
    expect(within(article).getByText("Indata · Mötesdatum")).toBeTruthy();
    expect(within(article).getByText("Steg 3 · Sammanfatta beslut · decisions")).toBeTruthy();
  });

  it("shows a document step's template file, bindings, format, title and file name, read-only", async () => {
    const { article, container } = card(4);
    expect(within(article).getByText("Protokollmall.docx")).toBeTruthy();
    expect(within(article).getByText("meeting_date")).toBeTruthy();
    expect(within(article).getByText("decisions")).toBeTruthy();
    expect(within(article).getByText("Föregående steg")).toBeTruthy();
    expect(within(article).getByText("PDF")).toBeTruthy();
    expect(within(article).getByText("protokoll-", { exact: false })).toBeTruthy();
    expect(within(article).getAllByText("Indata · Mötesdatum").length).toBeGreaterThanOrEqual(3);
    expect(
      container.querySelectorAll("input, textarea, select, button, [contenteditable]")
    ).toHaveLength(0);
    await expectNoAxeViolations(container);
  });
});
