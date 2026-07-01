import type { FlowStep } from "@intric/intric-js";
import type { FlowEditor } from "$lib/features/flows/FlowEditor";
import type { Intric } from "@intric/intric-js";
import { get } from "svelte/store";
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
import { getTemplateFillErrorMessage } from "$lib/features/flows/templateFillErrors";
import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";

/**
 * Manages template fill state: file listing, inspection, binding management,
 * and all derived template-related values.
 */
type TemplateFillContext = {
  activeStep: FlowStep;
  steps: FlowStep[];
  formSchema: TemplateBindingFormSchema | undefined;
  updateStep: (field: string, value: unknown) => void;
};

export class FlowTemplateState {
  #intric: Intric;
  #flowEditor: FlowEditor;

  availableFiles: FlowTemplateAssetOption[] = $state([]);
  filesLoaded = $state(false);
  filesLoading = $state(false);
  inspecting = $state(false);
  inspection: FlowTemplateInspection | null = $state(null);
  configError: string | null = $state(null);
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

  constructor(opts: { intric: Intric; flowEditor: FlowEditor }) {
    this.#intric = opts.intric;
    this.#flowEditor = opts.flowEditor;
  }

  #getFlowId(): string {
    return (get(this.#flowEditor.state.resource) as { id: string }).id;
  }

  async loadFiles(force = false) {
    if (!force && (this.filesLoading || this.filesLoaded)) return;
    this.filesLoading = true;
    try {
      const response = await this.#intric.flows.templates.list({ id: this.#getFlowId() });
      this.availableFiles = Array.isArray(response)
        ? response
        : Array.isArray((response as { items?: FlowTemplateAssetOption[] })?.items)
          ? ((response as { items: FlowTemplateAssetOption[] }).items ?? [])
          : [];
      this.filesLoaded = true;
    } catch (error) {
      this.configError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.flow_template_fill_template_help())
      );
    } finally {
      this.filesLoading = false;
    }
  }

  async inspectFile(assetId: string, options: { persist: boolean }, context: TemplateFillContext) {
    this.inspecting = true;
    this.configError = null;
    try {
      const result = await this.#intric.flows.templates.inspect({
        id: this.#getFlowId(),
        fileId: assetId
      });
      this.inspection = result;
      if (options.persist) {
        const config = getTemplateFillOutputConfig(context.activeStep);
        context.updateStep(
          "output_config",
          applyTemplateInspection(
            config,
            result,
            buildTemplateBindingAutoSuggestions({
              placeholders: result.placeholders.map((item: { name: string }) => item.name),
              steps: context.steps,
              currentStepOrder: context.activeStep.step_order,
              formSchema: context.formSchema
            })
          )
        );
      }
    } catch (error) {
      this.configError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.flow_template_fill_template_help())
      );
    } finally {
      this.inspecting = false;
    }
  }

  async handleFileSelection(assetId: string, context: TemplateFillContext) {
    if (!assetId) {
      const config = getTemplateFillOutputConfig(context.activeStep);
      context.updateStep("output_config", {
        ...config,
        template_asset_id: undefined,
        template_name: undefined,
        placeholders: [],
        bindings: {}
      });
      this.inspection = null;
      return;
    }
    await this.inspectFile(assetId, { persist: true }, context);
  }

  async handleUpload(event: Event, context: TemplateFillContext) {
    const input = event.currentTarget as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".docx")) {
      this.configError = m.flow_template_fill_template_help();
      if (input) input.value = "";
      return;
    }
    this.configError = null;
    this.inspecting = true;
    try {
      const uploaded = await this.#intric.flows.templates.upload({
        id: this.#getFlowId(),
        file
      });
      await this.loadFiles(true);
      await this.inspectFile(uploaded.id, { persist: true }, context);
      toast.success(m.flow_template_fill_upload_action());
    } catch (error) {
      this.configError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.flow_template_fill_template_help())
      );
    } finally {
      this.inspecting = false;
      if (input) input.value = "";
    }
  }

  async download(resolvedAssetId: string) {
    try {
      const { url } = await this.#intric.flows.templates.signedUrl({
        id: this.#getFlowId(),
        fileId: resolvedAssetId,
        contentDisposition: "attachment"
      });
      window.open(url, "_blank");
    } catch (error) {
      console.error("Failed to download template", error);
      this.configError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.error_downloading_file())
      );
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
    const nextKey =
      activeStep && isTemplateFill ? `${activeStep.id ?? "new"}:${resolvedAssetId ?? ""}` : null;
    if (nextKey !== this.#lastInspectionKey) {
      this.#lastInspectionKey = nextKey;
      this.inspection = null;
      this.configError = null;
      return resolvedAssetId; // caller should trigger inspection if non-null
    }
    return null; // no change needed
  }
}
