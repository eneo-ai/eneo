import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";

import type { Flow, Intric } from "@intric/intric-js";

import { createFlowEditor } from "./FlowEditor";

function makeFlow(metadataJson: Flow["metadata_json"] = null): Flow {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    tenant_id: "tenant-1",
    space_id: "space-1",
    name: "Flow",
    description: null,
    published_version: null,
    metadata_json: metadataJson,
    data_retention_days: null,
    created_at: null,
    updated_at: null,
    steps: []
  };
}

function makeIntric(): Intric {
  return {
    files: {
      delete: vi.fn()
    },
    flows: {
      update: vi.fn(),
      assistants: {
        create: vi.fn(),
        get: vi.fn(),
        update: vi.fn()
      }
    },
    assistants: {
      listPrompts: vi.fn()
    }
  } as unknown as Intric;
}

describe("FlowEditor metadata commands", () => {
  it("replaces form schema fields with persisted field shape", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "replace-form",
      flow: makeFlow({
        wizard: { transcription_enabled: true },
        form_schema: { fields: [{ name: "old", type: "text", order: 1 }] }
      })
    });

    expect(metadataJson).toEqual({
      wizard: { transcription_enabled: true },
      form_schema: {
        fields: [
          { name: "titel", type: "text", required: true, order: 1 },
          { name: "val", type: "select", required: false, order: 2, options: ["A"] }
        ]
      }
    });
    expect(hasUnsavedChanges).toBe(true);
  });

  it("keeps explicit empty form schema fields", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "empty-form",
      flow: makeFlow({ owner: "wizard" })
    });

    expect(metadataJson).toEqual({
      owner: "wizard",
      form_schema: { fields: [] }
    });
    expect(hasUnsavedChanges).toBe(true);
  });

  it("patches wizard metadata while preserving existing wizard and metadata keys", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "wizard",
      flow: makeFlow({
        owner: "wizard",
        wizard: {
          transcription_enabled: true,
          transcription_language: "sv"
        }
      })
    });

    expect(metadataJson).toEqual({
      owner: "wizard",
      wizard: {
        transcription_enabled: false,
        transcription_language: "sv",
        transcription_model: { id: "model-1" }
      }
    });
    expect(hasUnsavedChanges).toBe(true);
  });

  it("replaces invalid wizard metadata with the requested patch", () => {
    const { metadataJson, hasUnsavedChanges } = renderEditorMetadata({
      operation: "wizard",
      flow: makeFlow({
        owner: "wizard",
        wizard: "invalid"
      })
    });

    expect(metadataJson).toEqual({
      owner: "wizard",
      wizard: {
        transcription_enabled: false,
        transcription_model: { id: "model-1" }
      }
    });
    expect(hasUnsavedChanges).toBe(true);
  });
});

function renderEditorMetadata({
  flow,
  operation
}: {
  flow: Flow;
  operation: "replace-form" | "empty-form" | "wizard";
}): { metadataJson: unknown; hasUnsavedChanges: boolean } {
  const editor = createFlowEditor({ flow, intric: makeIntric() });
  try {
    if (operation === "replace-form") {
      editor.replaceFormSchemaFields([
        { name: " titel ", type: "email", required: true, options: ["ignored"] },
        { name: "val", type: "select", required: false, options: [" A ", ""] }
      ]);
    } else if (operation === "empty-form") {
      editor.replaceFormSchemaFields([]);
    } else {
      editor.setWizardMetadata({ transcription_model: { id: "model-1" } });
      editor.setTranscriptionEnabled(false);
    }

    const update = get(editor.state.update);
    const currentChanges = get(editor.state.currentChanges);
    return {
      metadataJson: update.metadata_json,
      hasUnsavedChanges: currentChanges.hasUnsavedChanges
    };
  } finally {
    editor.destroy();
  }
}
