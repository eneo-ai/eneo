import { get } from "svelte/store";
import { describe, expect, it, vi } from "vitest";

import type { Flow, Intric } from "@intric/intric-js";

import { createFlowEditor } from "./FlowEditor";

function makeFlow(metadataJson: Flow["metadata_json"] = null, overrides: Partial<Flow> = {}): Flow {
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
    steps: [],
    ...overrides
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

describe("FlowEditor basic settings commands", () => {
  it("sets the name while preserving neighboring fields", () => {
    const flow = makeFlow(
      { owner: "metadata" },
      { description: "Description", data_retention_days: 30 }
    );
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      const originalSteps = get(editor.state.update).steps;

      editor.setName("Renamed flow");

      const { update, hasUnsavedChanges } = readEditorState(editor);
      expect(update.name).toBe("Renamed flow");
      expect(update.description).toBe("Description");
      expect(update.metadata_json).toEqual({ owner: "metadata" });
      expect(update.steps).toBe(originalSteps);
      expect(update.data_retention_days).toBe(30);
      expect(hasUnsavedChanges).toBe(true);
    } finally {
      editor.destroy();
    }
  });

  it("accepts an empty name while preserving publish-readiness behavior", () => {
    const editor = createFlowEditor({ flow: makeFlow(), intric: makeIntric() });
    try {
      editor.setName("");

      const { update, hasUnsavedChanges } = readEditorState(editor);
      expect(update.name).toBe("");
      expect(hasUnsavedChanges).toBe(true);
    } finally {
      editor.destroy();
    }
  });

  it("sets the description string while preserving neighboring fields", () => {
    const flow = makeFlow(
      { owner: "metadata" },
      { name: "Original name", description: "Original", data_retention_days: 14 }
    );
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      const originalSteps = get(editor.state.update).steps;

      editor.setDescription("Updated description");

      const { update, hasUnsavedChanges } = readEditorState(editor);
      expect(update.name).toBe("Original name");
      expect(update.description).toBe("Updated description");
      expect(update.metadata_json).toEqual({ owner: "metadata" });
      expect(update.steps).toBe(originalSteps);
      expect(update.data_retention_days).toBe(14);
      expect(hasUnsavedChanges).toBe(true);

      editor.setDescription("");
      expect(get(editor.state.update).description).toBe("");
    } finally {
      editor.destroy();
    }
  });

  it("sets data retention while preserving zero, null, and neighboring fields", () => {
    const flow = makeFlow({ owner: "metadata" }, { name: "Flow", description: "Description" });
    const editor = createFlowEditor({ flow, intric: makeIntric() });
    try {
      const originalSteps = get(editor.state.update).steps;

      editor.setDataRetentionDays(0);
      expect(get(editor.state.update).data_retention_days).toBe(0);

      editor.setDataRetentionDays(7);
      let update = get(editor.state.update);
      expect(update.data_retention_days).toBe(7);
      expect(update.name).toBe("Flow");
      expect(update.description).toBe("Description");
      expect(update.metadata_json).toEqual({ owner: "metadata" });
      expect(update.steps).toBe(originalSteps);
      expect(get(editor.state.currentChanges).hasUnsavedChanges).toBe(true);

      editor.setDataRetentionDays(Number.NaN);
      update = get(editor.state.update);
      expect(update.data_retention_days).toBeNull();

      editor.setDataRetentionDays(null);
      const { update: finalUpdate, hasUnsavedChanges } = readEditorState(editor);
      expect(finalUpdate.data_retention_days).toBeNull();
      expect(hasUnsavedChanges).toBe(false);
    } finally {
      editor.destroy();
    }
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

function readEditorState(editor: ReturnType<typeof createFlowEditor>): {
  update: Flow;
  hasUnsavedChanges: boolean;
} {
  return {
    update: get(editor.state.update),
    hasUnsavedChanges: get(editor.state.currentChanges).hasUnsavedChanges
  };
}
