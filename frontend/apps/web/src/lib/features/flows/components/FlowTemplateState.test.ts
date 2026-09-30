import { describe, expect, it, vi } from "vitest";
import { writable } from "svelte/store";
import { EneoError, type Eneo, type FlowStep } from "@eneo/eneo-js";
import type { FlowEditor } from "../FlowEditor";
import type { FlowTemplateInspection } from "../templateFillConfig";
import { FlowTemplateState } from "./FlowTemplateState.svelte.ts";

vi.mock("svelte-sonner", () => ({ toast: { success: vi.fn() } }));
import { toast } from "svelte-sonner";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => (resolve = done));
  return { promise, resolve };
}

function step(id = "one"): FlowStep {
  return {
    id,
    assistant_id: `assistant-${id}`,
    step_order: 2,
    input_source: "previous_step",
    input_type: "text",
    output_type: "docx",
    output_mode: "template_fill",
    output_config: { bindings: { body: "" }, placeholders: ["body"] }
  };
}

function inspection(assetId: string): FlowTemplateInspection {
  return {
    asset_id: assetId,
    file_id: `file-${assetId}`,
    file_name: `${assetId}.docx`,
    placeholders: [{ name: "body", label: "Body", kind: "rich", location: "body" }]
  };
}

function fixture() {
  let currentStep: FlowStep | null = step();
  const templates = {
    list: vi.fn(async () => []),
    upload: vi.fn(async () => ({ id: "uploaded" })),
    inspect: vi.fn(async ({ fileId }: { fileId: string }) => inspection(fileId))
  };
  const state = new FlowTemplateState({
    eneo: { flows: { templates } } as unknown as Eneo,
    flowEditor: { state: { resource: writable({ id: "flow" }) } } as unknown as FlowEditor
  });
  const updateStep = vi.fn((field: string, value: unknown) => {
    currentStep = { ...currentStep!, [field]: value };
  });
  const context = {
    activeStep: currentStep!,
    steps: [],
    formSchema: undefined,
    getStep: () => currentStep,
    updateStep
  };
  state.syncInspection(currentStep, true, null);
  return {
    state,
    templates,
    context,
    updateStep,
    setStep: (next: FlowStep | null) => {
      currentStep = next;
    },
    getStep: () => currentStep
  };
}

describe("FlowTemplateState", () => {
  it("shows an actionable library error and clears it after an explicit retry", async () => {
    const { state, templates } = fixture();
    templates.list.mockRejectedValueOnce(new Error("internal upstream failure"));
    await state.loadFiles();
    expect(state.filesError).toBeTruthy();
    expect(state.filesError).not.toContain("internal upstream");
    expect(state.canRetry).toBe(true);
    expect(state.filesLoading).toBe(false);
    await state.retry();
    expect(state.filesError).toBeNull();
    expect(state.filesLoaded).toBe(true);
    expect(templates.list).toHaveBeenCalledTimes(2);
  });

  it("offers replacement guidance instead of retrying a permanently invalid template", async () => {
    const { state, templates, context } = fixture();
    templates.inspect.mockRejectedValueOnce(
      new EneoError(
        "No controls",
        "RESPONSE",
        400,
        0,
        { code: "flow_template_no_controls" },
        { endpoint: "GET@test" }
      )
    );
    await state.handleFileSelection("invalid", context);
    expect(state.configError).toBeTruthy();
    expect(state.canRetry).toBe(false);
    await state.retry();
    expect(templates.inspect).toHaveBeenCalledTimes(1);
  });

  it("keeps the latest selection when inspections finish out of order", async () => {
    const { state, templates, context, updateStep } = fixture();
    const pending = deferred<FlowTemplateInspection>();
    templates.inspect.mockImplementationOnce(() => pending.promise);
    const older = state.handleFileSelection("old", context);
    await state.handleFileSelection("new", context);
    pending.resolve(inspection("old"));
    await older;
    expect(state.inspection?.asset_id).toBe("new");
    expect(updateStep).toHaveBeenCalledTimes(1);
  });

  it("does not show another step's late inspection or clear its loading state", async () => {
    const { state, templates, context } = fixture();
    const first = deferred<FlowTemplateInspection>();
    const second = deferred<FlowTemplateInspection>();
    templates.inspect
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const older = state.inspectFile("first", { persist: false }, context);
    const next = step("two");
    state.syncInspection(next, true, "second");
    const newer = state.inspectFile("second", { persist: false }, { ...context, activeStep: next });
    first.resolve(inspection("first"));
    await older;
    expect(state.inspection).toBeNull();
    expect(state.inspecting).toBe(true);
    second.resolve(inspection("second"));
    await newer;
    expect(state.inspection?.asset_id).toBe("second");
  });

  it("merges a completed inspection with edits made while it was pending", async () => {
    const { state, templates, context, setStep, updateStep } = fixture();
    const pending = deferred<FlowTemplateInspection>();
    templates.inspect.mockImplementationOnce(() => pending.promise);
    const selecting = state.handleFileSelection("new", context);
    setStep({
      ...context.activeStep,
      output_config: { bindings: { body: "{{step_1.output.text}}" } }
    });
    pending.resolve(inspection("new"));
    await selecting;
    expect(updateStep).toHaveBeenCalledWith(
      "output_config",
      expect.objectContaining({
        bindings: { body: "{{step_1.output.text}}" }
      })
    );
  });

  it("does not attach a template after its step is removed or stops filling templates", async () => {
    for (const next of [null, { ...step(), output_mode: "pass_through" as const }]) {
      const { state, templates, context, setStep, updateStep } = fixture();
      const pending = deferred<FlowTemplateInspection>();
      templates.inspect.mockImplementationOnce(() => pending.promise);
      const selecting = state.handleFileSelection("new", context);
      setStep(next);
      pending.resolve(inspection("new"));
      await selecting;
      expect(updateStep).not.toHaveBeenCalled();
    }
  });

  it("does not announce upload success when inspection fails, and retries without uploading twice", async () => {
    vi.mocked(toast.success).mockClear();
    const { state, templates, context } = fixture();
    templates.inspect.mockRejectedValueOnce(new Error("offline"));
    const input = { files: [new File(["fixture"], "template.docx")], value: "template.docx" };
    await state.handleUpload({ currentTarget: input } as unknown as Event, context);
    expect(toast.success).not.toHaveBeenCalled();
    expect(state.configError).toBeTruthy();
    expect(input.value).toBe("");
    await state.retry();
    expect(state.configError).toBeNull();
    expect(state.inspection?.asset_id).toBe("uploaded");
    expect(templates.upload).toHaveBeenCalledTimes(1);
  });
});
