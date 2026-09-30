import { describe, expect, it, vi } from "vitest";
import { writable } from "svelte/store";
import { EneoError, type Eneo, type FlowStep } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { createFlowEditor, type FlowEditor } from "../FlowEditor";
import type { FlowTemplateInspection } from "../templateFillConfig";
import { FlowTemplateState, type TemplateStepHost } from "./FlowTemplateState.svelte.ts";

vi.mock("svelte-sonner", () => ({ toast: { success: vi.fn() } }));
import { toast } from "svelte-sonner";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
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
    flowEditor: {
      state: { resource: writable({ id: "flow" }) },
      stepIdentity: (item: FlowStep) => item.id
    } as unknown as FlowEditor
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

  describe("an operation that outlives the step's first save", () => {
    function newStepFixture() {
      const tempStep: FlowStep = {
        id: "_temp_new",
        assistant_id: "",
        step_order: 1,
        input_source: "flow_input",
        input_type: "text",
        output_type: "docx",
        output_mode: "template_fill",
        output_config: { bindings: {}, placeholders: [] }
      };
      const templates = {
        list: vi.fn(async () => []),
        upload: vi.fn(async () => ({ id: "uploaded" })),
        inspect: vi.fn(async ({ fileId }: { fileId: string }) => inspection(fileId))
      };
      const flowUpdate = vi.fn(async ({ update }: { update: { steps: FlowStep[] } }) => ({
        id: "flow",
        name: "Flow",
        draft_revision: 1,
        steps: update.steps.map((saved) => ({ ...saved, id: "step-real" }))
      }));
      const eneo = {
        flows: { templates, update: flowUpdate, assistants: {} },
        files: { delete: vi.fn() }
      } as unknown as Eneo;
      const editor = createFlowEditor({
        flow: { id: "flow", name: "Flow", draft_revision: 0, steps: [] } as never,
        eneo
      });
      editor.state.update.update((flow) => ({ ...flow, steps: [tempStep] }));
      const state = new FlowTemplateState({ eneo, flowEditor: editor });
      const host: TemplateStepHost = {
        get steps() {
          return get(editor.state.update).steps ?? [];
        },
        formSchema: undefined,
        isPublished: false,
        replaceStep: (index, next) =>
          editor.state.update.update((flow) => ({
            ...flow,
            steps: (flow.steps ?? []).map((item, at) => (at === index ? next : item))
          }))
      };
      // The assistant is created, then autosave gives the step its server id.
      const giveIds = async () => {
        editor.state.update.update((flow) => ({
          ...flow,
          steps: (flow.steps ?? []).map((item) => ({ ...item, assistant_id: "assistant-new" }))
        }));
        await editor.flushFlowSaves();
      };
      return { editor, state, host, tempStep, templates, giveIds };
    }

    it("keeps a template chosen on a new step when its ids are assigned during inspection", async () => {
      const { editor, state, host, tempStep, templates, giveIds } = newStepFixture();
      try {
        const pending = deferred<FlowTemplateInspection>();
        templates.inspect.mockImplementationOnce(() => pending.promise);
        const context = state.contextFor(tempStep, host);
        state.syncInspection(tempStep, true, null);
        const selecting = state.handleFileSelection("library-asset", context);

        await giveIds();
        expect(host.steps[0]).toMatchObject({ id: "step-real", assistant_id: "assistant-new" });
        pending.resolve(inspection("library-asset"));
        await selecting;

        expect(host.steps[0].output_config).toMatchObject({ template_asset_id: "library-asset" });
        // The panel re-syncs with the step's new ids: same step, same view.
        expect(state.syncInspection(host.steps[0], true, "library-asset")).toBeNull();
        expect(state.inspection?.asset_id).toBe("library-asset");
        expect(state.inspecting).toBe(false);
      } finally {
        editor.destroy();
      }
    });
  });

  describe("a failure while another step is shown", () => {
    const offline = () => new Error("offline");

    it("is kept for its step and restored with its retry when that step is selected again", async () => {
      const { state, templates, context, updateStep } = fixture();
      const pending = deferred<FlowTemplateInspection>();
      templates.inspect.mockImplementationOnce(() => pending.promise);
      const selecting = state.handleFileSelection("replacement", context);

      state.syncInspection(step("two"), true, "asset-two");
      pending.reject(offline());
      await selecting;
      expect(state.configError).toBeNull();

      // Returning must show what failed, not silently inspect the old asset.
      expect(state.syncInspection(context.activeStep, true, "configured")).toBeNull();
      expect(state.configError).toBeTruthy();
      expect(state.canRetry).toBe(true);
      await state.retry();
      expect(templates.inspect).toHaveBeenLastCalledWith({ id: "flow", fileId: "replacement" });
      expect(state.configError).toBeNull();
      expect(state.inspection?.asset_id).toBe("replacement");
      expect(updateStep).toHaveBeenCalledTimes(1);
    });

    it("keeps an upload failure for its step and retries the upload", async () => {
      const { state, templates, context } = fixture();
      const pending = deferred<{ id: string }>();
      templates.upload.mockImplementationOnce(() => pending.promise);
      const input = { files: [new File(["fixture"], "template.docx")], value: "template.docx" };
      const uploading = state.handleUpload({ currentTarget: input } as unknown as Event, context);

      state.syncInspection(step("two"), true, "asset-two");
      pending.reject(offline());
      await uploading;

      expect(state.syncInspection(context.activeStep, true, "configured")).toBeNull();
      expect(state.configError).toBeTruthy();
      expect(state.canRetry).toBe(true);
      await state.retry();
      expect(templates.upload).toHaveBeenCalledTimes(2);
      expect(state.configError).toBeNull();
      expect(state.inspection?.asset_id).toBe("uploaded");
    });

    it("does not show one step's failure on another step", async () => {
      const { state, templates, context } = fixture();
      templates.inspect.mockRejectedValueOnce(offline());
      await state.handleFileSelection("replacement", context);
      expect(state.configError).toBeTruthy();

      state.syncInspection(step("two"), true, "asset-two");
      expect(state.configError).toBeNull();
      expect(state.canRetry).toBe(false);
    });
  });
});
