// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { tick } from "svelte";
import type { Flow, FlowStep, Intric } from "@intric/intric-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";
import type { FlowEditor } from "../FlowEditor";
import type { FlowFormField } from "../flowFormSchema";
import FlowFormSchemaEditorHarness from "./test-harnesses/FlowFormSchemaEditorHarness.svelte";

function makeFlow(fields: FlowFormField[]): Flow {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    tenant_id: "tenant-1",
    space_id: "space-1",
    name: "Flow",
    description: null,
    published_version: null,
    metadata_json: { form_schema: { fields } },
    data_retention_days: null,
    created_at: null,
    updated_at: null,
    steps: [] as FlowStep[]
  };
}

function makeIntric(): Intric {
  return {
    files: {
      delete: vi.fn()
    },
    flows: {
      update: vi.fn(async ({ flow, update }: { flow: Flow; update: Partial<Flow> }) => ({
        ...flow,
        ...update
      })),
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

function field(name: string, label: string, order = 1): FlowFormField {
  return {
    name,
    label,
    type: "text",
    required: false,
    order
  };
}

function renderHarness(fields: FlowFormField[]): { editor: FlowEditor } {
  let editor: FlowEditor | null = null;
  render(FlowFormSchemaEditorHarness, {
    flow: makeFlow(fields),
    intric: makeIntric(),
    onEditor: (value) => {
      editor = value;
    }
  });
  if (!editor) throw new Error("FlowFormSchemaEditorHarness did not expose the editor");
  return { editor };
}

function replaceStoreFields(editor: FlowEditor, fields: FlowFormField[]): void {
  editor.state.update.update((resource) => ({
    ...resource,
    metadata_json: {
      ...(resource.metadata_json ?? {}),
      form_schema: { fields }
    }
  }));
}

async function flushEffects(): Promise<void> {
  await tick();
  await tick();
}

async function addLocalField(label: string): Promise<void> {
  await fireEvent.click(screen.getByRole("button", { name: m.flow_form_add_field() }));
  const labelInputs = screen.getAllByPlaceholderText(m.flow_form_field_label());
  await fireEvent.input(labelInputs[labelInputs.length - 1], { target: { value: label } });
  await flushEffects();
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  localStorage.clear();
});

describe("FlowFormSchemaEditor conflicts", () => {
  it("re-normalizes store changes while the local buffer is clean", async () => {
    const { editor } = renderHarness([field("case_id", "Case")]);
    await flushEffects();

    replaceStoreFields(editor, [field("server_id", "Server")]);
    await flushEffects();

    expect(screen.queryByText(m.flow_form_schema_conflict_title())).toBeNull();
    expect(screen.getByDisplayValue("Server")).not.toBeNull();
  });

  it("shows an inline conflict when saved fields change during a meaningful local edit", async () => {
    const { editor } = renderHarness([field("case_id", "Case")]);
    await flushEffects();

    await addLocalField("Local field");
    replaceStoreFields(editor, [field("server_id", "Server")]);
    await flushEffects();

    expect(screen.getByText(m.flow_form_schema_conflict_title())).not.toBeNull();
  });

  it("keeps local edits through FlowEditor form-schema writes", async () => {
    const { editor } = renderHarness([field("case_id", "Case")]);
    await flushEffects();

    await addLocalField("Local field");
    replaceStoreFields(editor, [field("server_id", "Server")]);
    await flushEffects();

    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_form_schema_conflict_keep_local() })
    );
    await flushEffects();

    expect(screen.queryByText(m.flow_form_schema_conflict_title())).toBeNull();
    expect(screen.getByTestId("metadata-json").textContent).toContain("Local field");
    expect(screen.getByTestId("metadata-json").textContent).not.toContain("Server");
  });

  it("reloads the latest store fields when the user discards local edits", async () => {
    const { editor } = renderHarness([field("case_id", "Case")]);
    await flushEffects();

    await addLocalField("Local field");
    replaceStoreFields(editor, [field("server_id", "Server")]);
    await flushEffects();

    await fireEvent.click(
      screen.getByRole("button", { name: m.flow_form_schema_conflict_reload() })
    );
    await flushEffects();

    expect(screen.queryByText(m.flow_form_schema_conflict_title())).toBeNull();
    expect(screen.getByDisplayValue("Server")).not.toBeNull();
    expect(screen.queryByDisplayValue("Local field")).toBeNull();
  });

  it("does not show a conflict for a blank untouched local field", async () => {
    const { editor } = renderHarness([field("case_id", "Case")]);
    await flushEffects();

    await fireEvent.click(screen.getByRole("button", { name: m.flow_form_add_field() }));
    replaceStoreFields(editor, [field("server_id", "Server")]);
    await flushEffects();

    expect(screen.queryByText(m.flow_form_schema_conflict_title())).toBeNull();
    expect(screen.getByDisplayValue("Server")).not.toBeNull();
  });

  it("does not show a conflict after a blank local field is added and removed", async () => {
    const { editor } = renderHarness([field("case_id", "Case")]);
    await flushEffects();

    await fireEvent.click(screen.getByRole("button", { name: m.flow_form_add_field() }));
    const deleteButtons = screen.getAllByRole("button", { name: m.delete() });
    await fireEvent.click(deleteButtons[deleteButtons.length - 1]);
    replaceStoreFields(editor, [field("server_id", "Server")]);
    await flushEffects();

    expect(screen.queryByText(m.flow_form_schema_conflict_title())).toBeNull();
    expect(screen.getByDisplayValue("Server")).not.toBeNull();
  });
});
