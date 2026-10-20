/** Test-only: one flow with every step kind, every parameter set. */
import type { FlowNames } from "./flow-step-summary";
import type { FlowFunctionPublic, FlowPublic } from "./types";

export const flowFixture: FlowPublic = {
  id: "flow-1",
  space_id: "space-1",
  name: "Mötesprotokoll",
  description:
    "Transkriberar en mötesinspelning, pausar för granskning och fyller protokollmallen.",
  published_version: 3,
  has_unpublished_changes: true,
  revision: 4,
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
        description: "Plockar ut besluten ur det granskade transkriptet.",
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
            required: ["decisions"],
            properties: {
              decisions: { type: "array", items: { type: "string" } },
              actions: { type: "array", items: { type: "string" } },
              kind: { type: "string", enum: ["Nämnd", "AU"] }
            }
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
      },
      {
        kind: "function",
        key: "chart",
        id: "s6",
        name: "Rita beslutsdiagram",
        purpose: "charts",
        tool: "render_chart",
        arguments: { data: "{{steps.summary.json.decisions}}", kind: "bar" }
      }
    ]
  }
};

export const namesFixture: FlowNames = {
  modelName: (id) => (id === "model-1" ? "GPT-5.2" : null),
  transcriptionModelName: (id) => (id === "tm-1" ? "KB-Whisper large" : null),
  collectionName: (id) => (id === "collection-1" ? "Delegationsordning" : null),
  websiteName: (id) => (id === "website-1" ? "kommunen.se" : null),
  fileName: (id) => (id === "file-1" ? "Protokollmall.docx" : null)
};

/** What the space can call: charts served, compute enabled but unserved, the rest off. */
export const functionsFixture: FlowFunctionPublic[] = [
  { purpose: "web_search", enabled_in_space: false, available: false, provider: null, tools: [] },
  {
    purpose: "image_generation",
    enabled_in_space: false,
    available: false,
    provider: null,
    tools: []
  },
  {
    purpose: "file_analysis",
    enabled_in_space: false,
    available: false,
    provider: null,
    tools: []
  },
  {
    purpose: "file_creation",
    enabled_in_space: false,
    available: false,
    provider: null,
    tools: []
  },
  {
    purpose: "charts",
    enabled_in_space: true,
    available: true,
    provider: "Diagramtjänsten",
    tools: [
      {
        name: "render_chart",
        description: "Ritar ett diagram av data.\nAndra raden.",
        input_schema: {
          type: "object",
          required: ["data"],
          properties: { data: { type: "string" }, kind: { type: "string" } }
        }
      },
      { name: "render_table", description: "Ritar en tabell.", input_schema: {} }
    ]
  },
  { purpose: "compute", enabled_in_space: true, available: false, provider: null, tools: [] }
];
