import type { FlowStep } from "@eneo/eneo-js";
import type { FlowEditor } from "$lib/features/flows/FlowEditor";
import { EneoError, type Eneo } from "@eneo/eneo-js";
import { get } from "svelte/store";
import { SvelteMap } from "svelte/reactivity";
import { m } from "$lib/paraglide/messages";
import { toast } from "$lib/components/toast";
import {
  applyTemplateInspection,
  buildTemplateBindingAutoSuggestions,
  buildTemplateBindingSuggestions,
  type FlowTemplateAssetOption,
  getTemplateFillOutputConfig,
  getTemplateFillReadiness,
  groupTemplateBindingSuggestions,
  listTemplateBindingRows,
  listTemplatePlaceholders,
  resolveTemplateAssetSelection,
  type TemplateBindingFormSchema,
  type TemplateBindingSuggestionLabels,
  type FlowTemplateInspection
} from "$lib/features/flows/templateFillConfig";
import {
  describeFlowApiError,
  getFlowRuntimeErrorMessage
} from "$lib/features/flows/flowRuntimeErrorMapping";

/**
 * Manages template fill state: file listing, inspection, binding management,
 * and all derived template-related values.
 */
type TemplateFillContext = {
  activeStep: FlowStep;
  steps: FlowStep[];
  formSchema: TemplateBindingFormSchema | undefined;
  getStep: () => FlowStep | null;
  updateStep: (field: string, value: unknown) => void;
};

export class FlowTemplateState {
  #eneo: Eneo;
  #flowEditor: FlowEditor;

  availableFiles: FlowTemplateAssetOption[] = $state([]);
  filesLoaded = $state(false);
  filesLoading = $state(false);
  inspecting = $state(false);
  inspection: FlowTemplateInspection | null = $state(null);
  configError: string | null = $state(null);
  filesError: string | null = $state(null);
  #retryAction: (() => Promise<unknown>) | null = $state(null);
  #visibleStepKey: string | null = null;
  #requests = new SvelteMap<string, number>();
  #requestSequence = 0;
  #listSequence = 0;
  #downloadSequence = 0;
  #lastInspectionKey: string | null = null;

  readonly bindingLabels: TemplateBindingSuggestionLabels = {
    formField: m.flow_template_fill_group_form(),
    aiSection: m.flow_template_fill_group_steps(),
    systemVariable: m.flow_template_fill_group_system(),
    formFieldItem: (name: string) => m.flow_template_fill_source_form({ name }),
    stepTextItem: (stepLabel: string) => m.flow_template_fill_source_step_text({ name: stepLabel }),
    stepJsonItem: (stepLabel: string) => m.flow_template_fill_source_step_json({ name: stepLabel }),
    todayDate: m.flow_template_fill_source_date(),
    leaveEmpty: m.flow_template_fill_leave_empty(),
    emptyValue: ""
  };

  constructor(opts: { eneo: Eneo; flowEditor: FlowEditor }) {
    this.#eneo = opts.eneo;
    this.#flowEditor = opts.flowEditor;
  }

  #getFlowId(): string {
    return (get(this.#flowEditor.state.resource) as { id: string }).id;
  }

  async loadFiles(force = false) {
    if (!force && (this.filesLoading || this.filesLoaded)) return;
    this.filesLoading = true;
    this.filesError = null;
    const request = ++this.#listSequence;
    try {
      const response = await this.#eneo.flows.templates.list({ id: this.#getFlowId() });
      if (request !== this.#listSequence) return;
      this.availableFiles = Array.isArray(response)
        ? response
        : Array.isArray((response as { items?: FlowTemplateAssetOption[] })?.items)
          ? ((response as { items: FlowTemplateAssetOption[] }).items ?? [])
          : [];
      this.filesLoaded = true;
    } catch (error) {
      if (request === this.#listSequence) {
        this.filesError = this.#errorMessage(error, m.flow_template_fill_list_failed());
      }
    } finally {
      if (request === this.#listSequence) this.filesLoading = false;
    }
  }

  #stepKey(step: FlowStep): string {
    return step.assistant_id || step.id || `new:${step.step_order}`;
  }

  #begin(context: TemplateFillContext) {
    this.#downloadSequence += 1;
    const key = this.#stepKey(context.activeStep);
    const sequence = ++this.#requestSequence;
    this.#requests.set(key, sequence);
    if (key === this.#visibleStepKey) {
      this.inspecting = true;
      this.configError = null;
      this.#retryAction = null;
    }
    return { key, sequence };
  }

  #isLatest(request: { key: string; sequence: number }) {
    return this.#requests.get(request.key) === request.sequence;
  }

  #canRetry(error: unknown): boolean {
    return (
      !(error instanceof EneoError) ||
      error.status === 0 ||
      error.status === 408 ||
      error.status === 429 ||
      error.status >= 500
    );
  }

  #finish(request: { key: string; sequence: number }) {
    if (!this.#isLatest(request)) return;
    this.#requests.delete(request.key);
    if (request.key === this.#visibleStepKey) this.inspecting = false;
  }

  #errorMessage(error: unknown, fallback: string): string {
    if (this.#canRetry(error) && !describeFlowApiError(error)) return fallback;
    return getFlowRuntimeErrorMessage(error, fallback);
  }

  get canRetry() {
    return this.configError ? Boolean(this.#retryAction) : Boolean(this.filesError);
  }

  async retry() {
    if (this.#retryAction) await this.#retryAction();
    else if (this.filesError) await this.loadFiles(true);
  }

  async inspectFile(assetId: string, options: { persist: boolean }, context: TemplateFillContext) {
    const request = this.#begin(context);
    try {
      return await this.#inspect(assetId, options, context, request);
    } finally {
      this.#finish(request);
    }
  }

  async #inspect(
    assetId: string,
    options: { persist: boolean },
    context: TemplateFillContext,
    request: { key: string; sequence: number }
  ): Promise<boolean> {
    try {
      const result = await this.#eneo.flows.templates.inspect({
        id: this.#getFlowId(),
        fileId: assetId
      });
      if (!this.#isLatest(request)) return false;
      const step = context.getStep();
      if (!step || step.output_mode !== "template_fill") return false;
      if (request.key === this.#visibleStepKey) {
        this.inspection = result;
        this.#lastInspectionKey = `${request.key}:${assetId}`;
      }
      if (options.persist) {
        const config = getTemplateFillOutputConfig(step);
        context.updateStep(
          "output_config",
          applyTemplateInspection(
            config,
            result,
            buildTemplateBindingAutoSuggestions({
              placeholders: result.placeholders.map((item: { name: string }) => item.name),
              steps: context.steps,
              currentStepOrder: step.step_order,
              formSchema: context.formSchema
            })
          )
        );
      }
      return true;
    } catch (error) {
      if (this.#isLatest(request) && request.key === this.#visibleStepKey) {
        this.configError = this.#errorMessage(error, m.flow_template_fill_inspection_failed());
        this.#retryAction = this.#canRetry(error)
          ? () => this.inspectFile(assetId, options, context)
          : null;
      }
      return false;
    }
  }

  async handleFileSelection(assetId: string, context: TemplateFillContext) {
    if (!assetId) {
      const request = this.#begin(context);
      const step = context.getStep();
      if (!step) {
        this.#finish(request);
        return;
      }
      const config = getTemplateFillOutputConfig(step);
      context.updateStep("output_config", {
        ...config,
        template_asset_id: undefined,
        template_name: undefined,
        template_checksum: undefined,
        placeholders: [],
        bindings: {}
      });
      this.inspection = null;
      this.#finish(request);
      return;
    }
    await this.inspectFile(assetId, { persist: true }, context);
  }

  async handleUpload(event: Event, context: TemplateFillContext) {
    const input = event.currentTarget as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".docx")) {
      this.configError = m.flow_error_flow_template_unsupported_extension();
      this.#retryAction = null;
      if (input) input.value = "";
      return;
    }
    await this.#upload(file, context);
    if (input) input.value = "";
  }

  async #upload(file: File, context: TemplateFillContext) {
    const request = this.#begin(context);
    try {
      const uploaded = await this.#eneo.flows.templates.upload({
        id: this.#getFlowId(),
        file
      });
      await this.loadFiles(true);
      const ready = await this.#inspect(uploaded.id, { persist: true }, context, request);
      if (ready) toast.success(m.flow_template_fill_upload_success());
    } catch (error) {
      if (this.#isLatest(request) && request.key === this.#visibleStepKey) {
        this.configError = this.#errorMessage(error, m.flow_template_fill_upload_failed());
        this.#retryAction = this.#canRetry(error) ? () => this.#upload(file, context) : null;
      }
    } finally {
      this.#finish(request);
    }
  }

  async download(resolvedAssetId: string) {
    const stepKey = this.#visibleStepKey;
    const sequence = ++this.#downloadSequence;
    this.configError = null;
    this.#retryAction = null;
    try {
      const { url } = await this.#eneo.flows.templates.signedUrl({
        id: this.#getFlowId(),
        fileId: resolvedAssetId,
        contentDisposition: "attachment"
      });
      window.open(url, "_blank");
    } catch (error) {
      if (stepKey === this.#visibleStepKey && sequence === this.#downloadSequence) {
        this.configError = this.#errorMessage(error, m.error_downloading_file());
        this.#retryAction = this.#canRetry(error) ? () => this.download(resolvedAssetId) : null;
      }
    }
  }

  /** Build all derived template values from the current step */
  getDerived(
    activeStep: FlowStep | null,
    steps: FlowStep[],
    formSchema: TemplateBindingFormSchema | undefined
  ) {
    const config = getTemplateFillOutputConfig(activeStep);
    const placeholders = listTemplatePlaceholders(this.inspection, config);
    const suggestions = activeStep
      ? buildTemplateBindingSuggestions({
          steps,
          currentStepOrder: activeStep.step_order,
          labels: this.bindingLabels,
          formSchema
        })
      : [];
    const suggestionGroups = groupTemplateBindingSuggestions(suggestions, this.bindingLabels);
    const autoBindings = activeStep
      ? buildTemplateBindingAutoSuggestions({
          placeholders: placeholders.map((item) => item.name),
          steps,
          currentStepOrder: activeStep.step_order,
          formSchema
        })
      : {};
    const bindingRows = listTemplateBindingRows({
      inspection: this.inspection,
      currentConfig: config,
      suggestions,
      autoSuggestions: autoBindings,
      labels: this.bindingLabels
    });
    const readiness = getTemplateFillReadiness(config);
    const orphanedRows = bindingRows.filter((row) => row.status === "orphaned");
    const hasSelection = Boolean(config.template_asset_id);
    const resolved = resolveTemplateAssetSelection(config, this.availableFiles);
    const unnamedStepWarning =
      activeStep !== null &&
      steps.some(
        (step) =>
          step.step_order < (activeStep.step_order ?? Number.MAX_SAFE_INTEGER) &&
          (!step.user_description || !step.user_description.trim())
      );
    const autoMatchableCount = bindingRows.filter(
      (row) => row.status === "missing" && Boolean(autoBindings[row.placeholderName])
    ).length;

    return {
      config,
      placeholders,
      suggestionGroups,
      autoBindings,
      bindingRows,
      readiness,
      orphanedRows,
      hasSelection,
      resolvedAssetId: resolved.assetId,
      selectedAsset: resolved.asset,
      unnamedStepWarning,
      autoMatchableCount
    };
  }

  /** Check and trigger inspection when step/asset changes */
  syncInspection(
    activeStep: FlowStep | null,
    isTemplateFill: boolean,
    resolvedAssetId: string | null
  ) {
    const stepKey = activeStep && isTemplateFill ? this.#stepKey(activeStep) : null;
    const nextKey = stepKey ? `${stepKey}:${resolvedAssetId ?? ""}` : null;
    if (nextKey !== this.#lastInspectionKey) {
      this.#downloadSequence += 1;
      this.#lastInspectionKey = nextKey;
      this.#visibleStepKey = stepKey;
      this.inspection = null;
      this.configError = null;
      this.#retryAction = null;
      this.inspecting = stepKey !== null && this.#requests.has(stepKey);
      if (this.inspecting) return null;
      return resolvedAssetId; // caller should trigger inspection if non-null
    }
    return null; // no change needed
  }
}
