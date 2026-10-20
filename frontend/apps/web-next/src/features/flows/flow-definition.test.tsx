// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowDefinition } from "./flow-definition";
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

afterEach(cleanup);

describe("FlowDefinition", () => {
  it("shows every input and every parameter of every step kind, read-only", async () => {
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

    // Transcribe: source, model, language, speakers.
    const transcribe = screen.getByRole("article", { name: "Steg 1: Transkribera mötet" });
    expect(within(transcribe).getByText("Transkribering")).toBeTruthy();
    expect(within(transcribe).getByText("Indata · Inspelning")).toBeTruthy();
    expect(within(transcribe).getByText("KB-Whisper large")).toBeTruthy();
    expect(within(transcribe).getByText("sv")).toBeTruthy();
    expect(
      within(transcribe).getByText("Identifiera talare, högst 6 · namnge från Deltagare")
    ).toBeTruthy();

    // Review: mode, target, time limit.
    const review = screen.getByRole("article", { name: "Steg 2: Granska transkriptet" });
    expect(within(review).getByText("Granskning")).toBeTruthy();
    expect(
      within(review).getByText("Redigera: granskaren kan ändra texten innan den godkänns")
    ).toBeTruthy();
    expect(within(review).getByText("Steg 1 · Transkribera mötet")).toBeTruthy();
    expect(within(review).getByText("Högst 7 dagar, sedan avbryts körningen")).toBeTruthy();

    // Llm: prompt, input template with reference badges, model and settings, knowledge, files, JSON output.
    const llm = screen.getByRole("article", { name: "Steg 3: Sammanfatta beslut" });
    expect(within(llm).getByText("Lista varje beslut med kort motivering.")).toBeTruthy();
    expect(within(llm).getByText("Steg 2 · Granska transkriptet")).toBeTruthy();
    expect(within(llm).getByText("Indata · Mötestyp")).toBeTruthy();
    expect(within(llm).getByText("GPT-5.2")).toBeTruthy();
    expect(within(llm).getByText("· temperature: 0")).toBeTruthy();
    expect(within(llm).getByText("Delegationsordning")).toBeTruthy();
    expect(within(llm).getByText("kommunen.se")).toBeTruthy();
    expect(within(llm).getByText("Indata · Inspelning")).toBeTruthy();
    expect(within(llm).getByText("JSON enligt schema", { exact: false })).toBeTruthy();
    expect(within(llm).getByText("decisions, actions")).toBeTruthy();
    expect(within(llm).getByText(/"type": "object"/)).toBeTruthy();

    // Compose: the template with its references.
    const compose = screen.getByRole("article", { name: "Steg 4: Inledning" });
    expect(within(compose).getByText("Protokoll fört", { exact: false })).toBeTruthy();
    expect(within(compose).getByText("Indata · Mötesdatum")).toBeTruthy();
    expect(within(compose).getByText("Steg 3 · Sammanfatta beslut · decisions")).toBeTruthy();

    // Document: template file, field bindings, format, title and file name.
    const document = screen.getByRole("article", { name: "Steg 5: Skapa protokoll" });
    expect(within(document).getByText("Protokollmall.docx")).toBeTruthy();
    expect(within(document).getByText("meeting_date")).toBeTruthy();
    expect(within(document).getByText("decisions")).toBeTruthy();
    expect(within(document).getByText("Föregående steg")).toBeTruthy();
    expect(within(document).getByText("PDF")).toBeTruthy();
    expect(within(document).getByText("protokoll-", { exact: false })).toBeTruthy();
    expect(within(document).getAllByText("Indata · Mötesdatum").length).toBeGreaterThanOrEqual(3);

    // Nothing is editable: no fields, no buttons.
    expect(
      container.querySelectorAll("input, textarea, select, button, [contenteditable]")
    ).toHaveLength(0);
    await expectNoAxeViolations(container);
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
