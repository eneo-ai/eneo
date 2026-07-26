/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import { toast } from "$lib/components/toast";
import { EneoError, type Flow, type FlowStep, type Eneo, type PromptSparse } from "@eneo/eneo-js";
import { derived, get, readonly, writable } from "svelte/store";
import { uid } from "uid";
import { shouldSaveAssistantImmediately } from "./assistantSavePolicy";
import { AssistantSaveManager } from "./flowAssistantSaveManager";
import {
  buildFlowFormSchemaMetadata,
  getFlowFormFieldVariableExpression,
  isFlowFormFieldBareAliasSafe,
  toPersistedFlowFormFields,
  type FlowFormField
} from "./flowFormSchema";
import { remapStepOrderTemplateTokens, replaceExactTemplateToken } from "./flowVariableTokens";
import { getFlowStepValidationIssues } from "./flowStepTypes";
import { m } from "$lib/paraglide/messages";
import {
  getFlowWizardMetadata,
  getUnifiedFlowSaveStatus,
  type FlowWizardMetadata
} from "./flowEditorMetadata";
import {
  canEditFlowRetentionContribution,
  isFlowRetentionDays,
  parseFlowRetentionDaysInput
} from "./flowEditorRetention";
import { stripTemporaryStepId, isValidStepIndex, buildBlankStep } from "./flowStepPayloadShaping";
import {
  computeStepConfigValidationIssues,
  hasDeletedStepReferences
} from "./flowStepConfigValidation";
import { rewriteStepBindings } from "./flowVariableReferenceRewriter";
import { computeStepOrderRemap } from "./flowStepOrderRemap";

type FlowEditorInitData = {
  flow: Flow;
  eneo: Eneo;
  onUpdateDone?: (flow: Flow) => void;
};

type FlowMetadataJson = NonNullable<Flow["metadata_json"]>;

const [getFlowEditor, setFlowEditor] = createContext<FlowEditor>("Edit a flow");

/**
 * The overrides a template can seed into a new step. Deliberately narrow: only
 * the output side and instruction, so a seeded step can never request an output
 * mode that needs extra config (http/template_fill) or an input override that
 * breaks chaining. The input side stays derived from position.
 */
export interface FlowStepCreationSeed {
  name?: string;
  output_type?: FlowStep["output_type"];
  output_mode?: "pass_through";
  prompt?: string;
}

function createFlowEditor(data: FlowEditorInitData) {
  type LoadedAssistant = Awaited<ReturnType<typeof data.eneo.flows.assistants.get>>;
  const assistantRevision = writable(0);
  const editor = createResourceEditor({
    eneo: data.eneo,
    resource: data.flow,
    defaults: {},
    updateResource: async (resource, changes) => {
      // Strip temp IDs before sending to API
      const cleanChanges = { ...changes } as Record<string, unknown>;
      if (cleanChanges.steps && Array.isArray(cleanChanges.steps)) {
        cleanChanges.steps = (cleanChanges.steps as FlowStep[]).map(stripTemporaryStepId);
      }
      const updated = (await data.eneo.flows.update({
        flow: resource,
        update: cleanChanges
      })) as Flow;

      // Reconcile temp IDs with real IDs after save
      const currentActiveId = get(activeStepId);
      if (currentActiveId?.startsWith?.("_temp_")) {
        const currentSteps = get(editor.state.update).steps ?? [];
        const activeStep = currentSteps.find((s: FlowStep) => s.id === currentActiveId);
        if (activeStep) {
          const realStep = updated.steps?.find(
            (s: FlowStep) => s.step_order === activeStep.step_order
          );
          if (realStep?.id) {
            activeStepId.set(realStep.id);
          }
        }
      }

      data.onUpdateDone?.(updated);
      return updated;
    },
    editableFields: {
      name: true,
      description: true,
      steps: [
        "id",
        "assistant_id",
        "step_order",
        "user_description",
        "input_source",
        "input_type",
        "input_contract",
        "output_mode",
        "output_type",
        "output_contract",
        "input_bindings",
        "output_classification_override",
        "review_policy",
        "input_config",
        "output_config"
      ],
      metadata_json: true,
      data_retention_days: true
    },
    manageAttachements: false
  });

  // Additional flow-specific stores
  const activeStepId = writable<string | null>(null);
  const validationErrors = writable<Map<string, string[]>>(new Map());
  const saveStatus = writable<"saved" | "saving" | "unsaved">("saved");
  // Which editor chapter a freshly-created step should open by default. Keyed by
  // step_order so it survives the temp→real id reconciliation. Template steps
  // land on the AI work section; blank steps land on "what".
  const newStepOpenIntent = writable<{ order: number; chapter: "ai" | "what" } | null>(null);

  // Derived: is the flow published?
  const isPublished = derived(editor.state.resource, ($resource) => {
    return $resource.published_version != null;
  });
  const canEditDataRetentionDays = derived(
    [editor.state.resource, isPublished],
    ([$resource, $isPublished]) =>
      canEditFlowRetentionContribution($resource.run_history_retention, $isPublished)
  );

  const assistantErrorPrefix = "assistant:";
  const flowErrorPrefix = "flow:";
  const typedIOValidationPrefix = `${flowErrorPrefix}typed-io:`;
  const stepConfigValidationPrefix = `${flowErrorPrefix}step-config:`;
  function setAssistantValidationError(assistantId: string, message: string | null) {
    validationErrors.update((current) => {
      const next = new Map(current);
      const key = `${assistantErrorPrefix}${assistantId}`;
      if (message) {
        next.set(key, [message]);
      } else {
        next.delete(key);
      }
      return next;
    });
  }

  function setFlowValidationError(code: string, message: string | null) {
    validationErrors.update((current) => {
      const next = new Map(current);
      const key = `${flowErrorPrefix}${code}`;
      if (message) {
        next.set(key, [message]);
      } else {
        next.delete(key);
      }
      return next;
    });
  }

  function replaceFlowValidationErrors(prefix: string, entries: Map<string, string[]>) {
    validationErrors.update((current) => {
      const next = new Map(current);
      for (const key of next.keys()) {
        if (key.startsWith(prefix)) {
          next.delete(key);
        }
      }
      for (const [key, value] of entries.entries()) {
        next.set(key, value);
      }
      return next;
    });
  }

  function syncTypedIOValidation(steps: FlowStep[] = get(editor.state.update).steps ?? []) {
    const issues = getFlowStepValidationIssues(steps);
    const entries = new Map<string, string[]>();
    for (const issue of issues) {
      entries.set(`${typedIOValidationPrefix}${issue.code}:${issue.stepOrder}`, [issue.code]);
    }
    replaceFlowValidationErrors(typedIOValidationPrefix, entries);
    syncStepConfigValidation(steps);
    pruneOrphanedAssistantErrors(steps);
    return issues;
  }

  function syncStepConfigValidation(steps: FlowStep[]) {
    replaceFlowValidationErrors(
      stepConfigValidationPrefix,
      computeStepConfigValidationIssues(steps, stepConfigValidationPrefix)
    );
  }

  function revalidateDeletedStepReferences() {
    const steps = get(editor.state.update).steps ?? [];
    const cachedPromptTextByAssistantId = new Map<string, string>();
    for (const step of steps) {
      const cached = assistantSaveManager.getCached(step.assistant_id);
      if (!cached || typeof cached !== "object") continue;
      const prompt = (cached as { prompt?: { text?: unknown } }).prompt;
      if (typeof prompt?.text === "string") {
        cachedPromptTextByAssistantId.set(step.assistant_id, prompt.text);
      }
    }
    if (!hasDeletedStepReferences(steps, cachedPromptTextByAssistantId)) {
      setFlowValidationError("deleted-step-reference", null);
    }
  }

  function pruneOrphanedAssistantErrors(steps: FlowStep[]) {
    const activeAssistantIds = new Set(steps.map((s) => s.assistant_id).filter(Boolean));
    validationErrors.update((current) => {
      let changed = false;
      const next = new Map(current);
      for (const key of next.keys()) {
        if (key.startsWith(assistantErrorPrefix)) {
          const assistantId = key.slice(assistantErrorPrefix.length);
          if (!activeAssistantIds.has(assistantId)) {
            next.delete(key);
            changed = true;
          }
        }
      }
      return changed ? next : current;
    });
  }

  function getFlowId(): string {
    return get(editor.state.resource).id;
  }

  const assistantSaveManager = new AssistantSaveManager<LoadedAssistant>({
    loadRemote: async (assistantId) =>
      data.eneo.flows.assistants.get({
        id: getFlowId(),
        assistantId
      }),
    saveRemote: async (assistantId, changes) =>
      data.eneo.flows.assistants.update({
        id: getFlowId(),
        assistantId,
        update: changes
      }),
    shouldSaveImmediately: shouldSaveAssistantImmediately,
    isDisabled: () => get(isPublished),
    getErrorMessage: (error) =>
      error instanceof EneoError ? error.getReadableMessage() : "assistant_save_failed",
    onValidationError: setAssistantValidationError,
    onSaved: () => {
      assistantRevision.update((value) => value + 1);
    },
    onPromptSaved: () => {
      revalidateDeletedStepReferences();
    }
  });
  const assistantSaveStatus = assistantSaveManager.status;

  async function loadAssistant(assistantId: string): Promise<LoadedAssistant | null> {
    return assistantSaveManager.load(assistantId);
  }

  async function updateAssistantImmediately(
    assistantId: string,
    changes: Record<string, unknown>
  ): Promise<void> {
    await assistantSaveManager.saveImmediately(assistantId, changes);
  }

  async function saveAssistant(assistantId: string, changes: Record<string, unknown>) {
    await assistantSaveManager.save(assistantId, changes);
  }

  async function flushAssistantSaves(): Promise<void> {
    await assistantSaveManager.flush();
  }

  async function flushFlowSaves(): Promise<void> {
    clearAutoSaveTimer();

    if (get(isPublished)) return;

    const { hasUnsavedChanges } = get(editor.state.currentChanges);
    if (!hasUnsavedChanges) {
      if (get(saveStatus) !== "unsaved") saveStatus.set("saved");
      return;
    }

    const steps = get(editor.state.update).steps ?? [];
    const stepIssues = syncTypedIOValidation(steps);
    if (
      stepIssues.length > 0 ||
      steps.some((s: FlowStep) => !s.assistant_id || s.assistant_id === "")
    ) {
      saveStatus.set("unsaved");
      return;
    }

    saveStatus.set("saving");
    await editor.saveChanges();

    const stillUnsaved = get(editor.state.currentChanges).hasUnsavedChanges;
    saveStatus.set(stillUnsaved ? "unsaved" : "saved");
    if (stillUnsaved) {
      throw new Error("Flow changes could not be saved before continuing.");
    }
  }

  async function flushSaves(): Promise<void> {
    await flushFlowSaves();
    await flushAssistantSaves();
  }

  // Unified save status combining flow + assistant saves
  const unifiedSaveStatus = derived([saveStatus, assistantSaveStatus], ([$flow, $assistant]) => {
    return getUnifiedFlowSaveStatus($flow, $assistant);
  });

  function setName(name: string): void {
    editor.state.update.update((resource) => ({
      ...resource,
      name
    }));
  }

  function setDescription(description: string): void {
    editor.state.update.update((resource) => ({
      ...resource,
      description
    }));
  }

  function setDataRetentionDays(days: number | null): void {
    if (!get(canEditDataRetentionDays)) return;
    if (days !== null && !isFlowRetentionDays(days)) return;

    editor.state.update.update((resource) => ({
      ...resource,
      data_retention_days: days
    }));
  }

  function setDataRetentionDaysFromInput(value: string): void {
    const days = parseFlowRetentionDaysInput(value);
    if (days === undefined) return;
    setDataRetentionDays(days);
  }

  function selectStep(stepId: string): void {
    const currentSteps = get(editor.state.update).steps ?? [];
    if (currentSteps.some((step) => step.id === stepId)) {
      activeStepId.set(stepId);
    }
  }

  function selectFirstStepIfUnselected(): void {
    if (get(activeStepId) !== null) return;

    const firstStepId = get(editor.state.update).steps?.[0]?.id;
    if (firstStepId) {
      activeStepId.set(firstStepId);
    }
  }

  function replaceStepAtIndex(index: number, step: FlowStep): void {
    const currentSteps = get(editor.state.update).steps ?? [];
    if (!isValidStepIndex(index, currentSteps)) return;

    const existingStepOrder = currentSteps[index].step_order;
    const nextSteps = [...currentSteps];
    nextSteps[index] = { ...step, step_order: existingStepOrder };
    editor.state.update.update((resource) => ({
      ...resource,
      steps: nextSteps
    }));
  }

  async function removeStepAtIndex(index: number): Promise<void> {
    const currentSteps = get(editor.state.update).steps ?? [];
    if (!isValidStepIndex(index, currentSteps)) return;

    const nextSteps = currentSteps
      .filter((_, stepIndex) => stepIndex !== index)
      .map((step, stepIndex) => ({ ...step, step_order: stepIndex + 1 }));

    await applyStepsWithSafeOrderRemap(nextSteps);
    const fallbackStepId = nextSteps[Math.min(index, nextSteps.length - 1)]?.id ?? null;
    activeStepId.set(fallbackStepId);
  }

  async function moveStepAtIndex(index: number, direction: -1 | 1): Promise<void> {
    const currentSteps = get(editor.state.update).steps ?? [];
    const newIndex = index + direction;
    if (!isValidStepIndex(index, currentSteps) || !isValidStepIndex(newIndex, currentSteps)) return;

    const reorderedSteps = [...currentSteps];
    [reorderedSteps[index], reorderedSteps[newIndex]] = [
      reorderedSteps[newIndex],
      reorderedSteps[index]
    ];
    const nextSteps = reorderedSteps.map((step, stepIndex) => ({
      ...step,
      step_order: stepIndex + 1
    }));

    await applyStepsWithSafeOrderRemap(nextSteps);
  }

  function updateMetadataJson(buildNext: (metadata: FlowMetadataJson) => FlowMetadataJson) {
    editor.state.update.update((resource) => ({
      ...resource,
      metadata_json: buildNext((resource.metadata_json ?? {}) as FlowMetadataJson)
    }));
  }

  function replaceFormSchemaFields(fields: FlowFormField[]): void {
    updateMetadataJson((metadata) =>
      buildFlowFormSchemaMetadata(metadata, toPersistedFlowFormFields(fields))
    );
  }

  function setWizardMetadata(patch: Partial<FlowWizardMetadata>): void {
    updateMetadataJson((metadata) => ({
      ...metadata,
      wizard: {
        ...getFlowWizardMetadata(metadata),
        ...patch
      }
    }));
  }

  function setTranscriptionEnabled(enabled: boolean): void {
    setWizardMetadata({ transcription_enabled: enabled });
  }

  // Debounced auto-save (500ms)
  let autoSaveTimer: ReturnType<typeof setTimeout> | null = null;

  function clearAutoSaveTimer() {
    if (autoSaveTimer) {
      clearTimeout(autoSaveTimer);
      autoSaveTimer = null;
    }
  }

  function scheduleAutoSave() {
    // CRITICAL: never auto-save when published
    if (get(isPublished)) return;

    const { hasUnsavedChanges } = get(editor.state.currentChanges);
    if (!hasUnsavedChanges) return;

    const stepIssues = syncTypedIOValidation((get(editor.state.update).steps ?? []) as FlowStep[]);
    if (stepIssues.length > 0) {
      clearAutoSaveTimer();
      if (get(saveStatus) !== "unsaved") saveStatus.set("unsaved");
      return;
    }

    if (get(saveStatus) !== "unsaved") saveStatus.set("unsaved");
    clearAutoSaveTimer();
    autoSaveTimer = setTimeout(async () => {
      // Double-check published state before saving
      if (get(isPublished)) return;

      // Don't save if any step has empty assistant_id (still being created)
      const steps = get(editor.state.update).steps ?? [];
      if (steps.some((s: FlowStep) => !s.assistant_id || s.assistant_id === "")) return;

      saveStatus.set("saving");
      try {
        await editor.saveChanges();
        saveStatus.set("saved");
      } catch {
        saveStatus.set("unsaved");
      }
    }, 500);
  }

  // Subscribe to update changes to trigger auto-save
  const unsubscribe = editor.state.currentChanges.subscribe(($changes) => {
    if ($changes.hasUnsavedChanges && !get(isPublished)) {
      scheduleAutoSave();
    }
  });
  const unsubscribeValidation = editor.state.update.subscribe(($update) => {
    syncTypedIOValidation(($update.steps ?? []) as FlowStep[]);
  });

  /**
   * Step creation. With no argument it appends a blank step (the instant path);
   * with a `seed` it applies a template's output shape plus a starter
   * instruction on the hidden assistant. The input side is always derived from
   * position, so a seeded step stays valid wherever it is added.
   *
   * Returns the created step's temporary id, or null when assistant creation
   * failed and the step was rolled back. Callers that chain steps must not
   * assume the last step in the list is the one they just asked for.
   */
  async function addStep(seed?: FlowStepCreationSeed): Promise<string | null> {
    const $update = get(editor.state.update);
    const currentSteps = $update.steps ?? [];
    const stepCount = currentSteps.length;
    const isFirst = stepCount === 0;
    const prevStep = stepCount > 0 ? currentSteps[stepCount - 1] : null;

    const tempId = `_temp_${uid(12)}`;
    const stepName = seed?.name ?? `Nytt steg ${stepCount + 1}`;
    const newStep = buildBlankStep({
      tempId,
      stepOrder: stepCount + 1,
      name: stepName,
      isFirst,
      prevStepOutputType: (prevStep as FlowStep)?.output_type,
      outputMode: seed?.output_mode,
      outputType: seed?.output_type
    });

    // Instant UI update
    editor.state.update.update((u) => ({
      ...u,
      steps: [...(u.steps ?? []), newStep as FlowStep]
    }));
    newStepOpenIntent.set({ order: stepCount + 1, chapter: seed ? "ai" : "what" });
    activeStepId.set(tempId);

    // Background: create hidden assistant
    try {
      const assistant = await data.eneo.flows.assistants.create({
        id: getFlowId(),
        name: stepName
      });
      // Wire the real assistant_id
      editor.state.update.update((u) => ({
        ...u,
        steps: (u.steps ?? []).map((s: FlowStep) =>
          s.id === tempId ? { ...s, assistant_id: assistant.id } : s
        )
      }));
      assistantSaveManager.primeCache(assistant.id, assistant);
      // Seed the starter instruction via the debounced assistant save (not an
      // immediate one) so it lands in the same ~500ms window as the step's
      // auto-save, collapsing the usual two "saved" flashes into one. The save
      // manager owns error handling, so a failed seed never discards the step.
      if (seed?.prompt) {
        void saveAssistant(assistant.id, { prompt: { text: seed.prompt } });
      }
    } catch {
      // Remove the step if assistant creation fails
      editor.state.update.update((u) => ({
        ...u,
        steps: (u.steps ?? []).filter((s: FlowStep) => s.id !== tempId)
      }));
      activeStepId.set(null);
      toast.error(m.flow_step_creation_failed());
      return null;
    }
    return tempId;
  }

  /** Insert step after a given step order */
  async function insertStepAfter(afterOrder: number): Promise<void> {
    const $update = get(editor.state.update);
    const currentSteps = [...($update.steps ?? [])];

    const tempId = `_temp_${uid(12)}`;
    const prevStep = currentSteps.find((s: FlowStep) => s.step_order === afterOrder);
    const isFirstInsert = afterOrder === 0;

    const defaultStepName = `Nytt steg ${afterOrder + 1}`;
    const newStep = buildBlankStep({
      tempId,
      stepOrder: afterOrder + 1,
      name: defaultStepName,
      isFirst: isFirstInsert,
      prevStepOutputType: (prevStep as FlowStep)?.output_type
    });

    // Renumber subsequent steps
    const updatedSteps = currentSteps.map((s: FlowStep) => {
      if (s.step_order > afterOrder) {
        return { ...s, step_order: s.step_order + 1 };
      }
      return s;
    });

    // Insert at correct position
    const insertIndex = updatedSteps.findIndex((s: FlowStep) => s.step_order > afterOrder);
    if (insertIndex >= 0) {
      updatedSteps.splice(insertIndex, 0, newStep as FlowStep);
    } else {
      updatedSteps.push(newStep as FlowStep);
    }

    editor.state.update.update((u) => ({ ...u, steps: updatedSteps }));
    activeStepId.set(tempId);

    // Background: create hidden assistant
    try {
      const assistant = await data.eneo.flows.assistants.create({
        id: getFlowId(),
        name: defaultStepName
      });
      editor.state.update.update((u) => ({
        ...u,
        steps: (u.steps ?? []).map((s: FlowStep) =>
          s.id === tempId ? { ...s, assistant_id: assistant.id } : s
        )
      }));
      assistantSaveManager.primeCache(assistant.id, assistant);
    } catch {
      // Remove the step and re-renumber
      editor.state.update.update((u) => {
        const filtered = (u.steps ?? []).filter((s: FlowStep) => s.id !== tempId);
        filtered.forEach((s: FlowStep, i: number) => {
          s.step_order = i + 1;
        });
        return { ...u, steps: filtered };
      });
      activeStepId.set(null);
      toast.error(m.flow_step_creation_failed());
    }
  }

  /**
   * Seed a three-step drafting chain: extract the facts, weigh them, then
   * write the summary.
   *
   * Built from `addStep`, which already owns assistant creation, positional
   * input derivation and save state, so this adds no second creation path. It
   * stays a plain sequence rather than a starter schema until a second starter
   * shows what would actually vary.
   */
  async function createDraftingChainStarter(): Promise<void> {
    const textStep = { output_type: "text", output_mode: "pass_through" } as const;

    // Every creation is checked. A failed step is rolled back by addStep, so an
    // unchecked failure would leave the summary sitting at an earlier position
    // where its own binding — {{step_2.output.text}} — would reference itself
    // and make the draft unpublishable. Earlier steps are left in place; they
    // are valid on their own.
    const extractStepId = await addStep({
      ...textStep,
      name: m.flow_starter_drafting_extract_name(),
      prompt: m.flow_starter_drafting_extract_prompt()
    });
    if (!extractStepId) return;

    const assessStepId = await addStep({
      ...textStep,
      name: m.flow_starter_drafting_assess_name(),
      prompt: m.flow_starter_drafting_assess_prompt()
    });
    if (!assessStepId) return;

    const summaryStepId = await addStep({
      ...textStep,
      name: m.flow_starter_drafting_summary_name(),
      prompt: m.flow_starter_drafting_summary_prompt()
    });

    // The summary reads both earlier steps. Seeds deliberately set only the
    // output side — the input side is derived from position — so this one
    // cross-step binding is applied here, matched by the id addStep returned
    // rather than by tail position.
    if (!summaryStepId) return;
    const steps = (get(editor.state.update).steps ?? []).map((step) =>
      step.id === summaryStepId
        ? {
            ...step,
            input_source: "all_previous_steps" as const,
            input_type: "text" as const,
            input_bindings: {
              // The step tokens stay in code: they are a runtime contract, not prose,
              // and a translated token would silently stop resolving.
              question:
                `${m.flow_starter_drafting_facts_label()}:\n{{step_1.output.text}}\n\n` +
                `${m.flow_starter_drafting_assessment_label()}:\n{{step_2.output.text}}`
            }
          }
        : step
    );
    editor.state.update.update((resource) => ({ ...resource, steps }));
    scheduleAutoSave();
  }

  async function listAssistantPrompts(assistantId: string): Promise<PromptSparse[]> {
    return data.eneo.assistants.listPrompts({ id: assistantId });
  }

  async function applyStepsWithSafeOrderRemap(nextSteps: FlowStep[]): Promise<void> {
    const previousSteps = [...(get(editor.state.update).steps ?? [])];
    const { rewrittenSteps, remapByOldOrder, deletedOrders, impactedDeletedBindingOrders } =
      computeStepOrderRemap(previousSteps, nextSteps);
    const impactedDeletedReferences = new Set<number>(impactedDeletedBindingOrders);

    editor.state.update.update((resource) => ({
      ...resource,
      steps: rewrittenSteps
    }));
    const stepIssues = syncTypedIOValidation(rewrittenSteps);
    if (stepIssues.length === 0) {
      scheduleAutoSave();
    } else {
      clearAutoSaveTimer();
    }

    for (const step of rewrittenSteps) {
      if (!step.assistant_id) continue;
      const assistant = await loadAssistant(step.assistant_id);
      if (!assistant || typeof assistant !== "object") continue;

      const prompt = (assistant as { prompt?: { text?: unknown; description?: unknown } }).prompt;
      const promptText = typeof prompt?.text === "string" ? prompt.text : "";
      if (!promptText) continue;

      const remapped = remapStepOrderTemplateTokens(promptText, remapByOldOrder, deletedOrders);
      if (!remapped.changed) continue;

      const nextPrompt = {
        text: remapped.text,
        description: typeof prompt?.description === "string" ? prompt.description : ""
      };
      await updateAssistantImmediately(step.assistant_id, { prompt: nextPrompt });
      for (const deletedReference of remapped.rewrittenDeletedReferences) {
        impactedDeletedReferences.add(deletedReference);
      }
    }

    if (impactedDeletedReferences.size > 0) {
      const sortedDeleted = [...impactedDeletedReferences].sort((a, b) => a - b).join(", ");
      setFlowValidationError(
        "deleted-step-reference",
        `Step references to removed step order(s) ${sortedDeleted} were marked for manual repair.`
      );
    } else {
      setFlowValidationError("deleted-step-reference", null);
    }
  }

  async function rewriteInputFieldVariableReferences(
    oldName: string,
    newName: string
  ): Promise<number> {
    const fromToken = oldName.trim();
    const toToken = getFlowFormFieldVariableExpression(newName);
    if (!fromToken || !toToken) return 0;

    function rewriteFormFieldReferences(text: string): string {
      let rewritten = replaceExactTemplateToken(text, `flow_input.${fromToken}`, toToken);
      if (isFlowFormFieldBareAliasSafe(fromToken)) {
        rewritten = replaceExactTemplateToken(rewritten, fromToken, toToken);
      }
      return rewritten;
    }

    let rewrittenCount = 0;
    const steps = get(editor.state.update).steps ?? [];
    for (const step of steps) {
      if (!step.assistant_id) continue;
      const assistant = await loadAssistant(step.assistant_id);
      if (!assistant || typeof assistant !== "object") continue;

      const prompt = (assistant as { prompt?: { text?: unknown; description?: unknown } }).prompt;
      const currentText = typeof prompt?.text === "string" ? prompt.text : "";
      const nextText = rewriteFormFieldReferences(currentText);
      if (nextText !== currentText) {
        const nextPrompt = {
          text: nextText,
          description: typeof prompt?.description === "string" ? prompt.description : ""
        };
        await updateAssistantImmediately(step.assistant_id, { prompt: nextPrompt });
        rewrittenCount += 1;
      }
    }

    const nextSteps = rewriteStepBindings(steps, rewriteFormFieldReferences);
    editor.state.update.update((resource) => ({ ...resource, steps: nextSteps }));
    scheduleAutoSave();

    return rewrittenCount;
  }

  async function rewriteStepNameVariableReferences({
    renamedStepOrder,
    oldName,
    newName
  }: {
    renamedStepOrder: number;
    oldName: string;
    newName: string;
  }): Promise<number> {
    const fromToken = oldName.trim();
    const toToken = newName.trim();
    if (!fromToken || !toToken || fromToken === toToken) return 0;

    let rewrittenCount = 0;
    const steps = (get(editor.state.update).steps ?? []).filter(
      (step) => step.step_order > renamedStepOrder
    );
    for (const step of steps) {
      if (!step.assistant_id) continue;
      const assistant = await loadAssistant(step.assistant_id);
      if (!assistant || typeof assistant !== "object") continue;
      const prompt = (assistant as { prompt?: { text?: unknown; description?: unknown } }).prompt;
      const currentText = typeof prompt?.text === "string" ? prompt.text : "";
      const nextText = replaceExactTemplateToken(currentText, fromToken, toToken);
      if (nextText === currentText) continue;
      const nextPrompt = {
        text: nextText,
        description: typeof prompt?.description === "string" ? prompt.description : ""
      };
      await updateAssistantImmediately(step.assistant_id, { prompt: nextPrompt });
      rewrittenCount += 1;
    }

    const allSteps = get(editor.state.update).steps ?? [];
    const nextSteps = rewriteStepBindings(
      allSteps,
      (question) => replaceExactTemplateToken(question, fromToken, toToken),
      (step) => step.step_order <= renamedStepOrder
    );
    editor.state.update.update((resource) => ({ ...resource, steps: nextSteps }));
    scheduleAutoSave();

    return rewrittenCount;
  }

  function destroy() {
    void flushFlowSaves().catch(() => {
      // Best-effort flush during teardown.
    });
    void flushAssistantSaves().catch(() => {
      // Best-effort flush during teardown.
    });
    assistantSaveManager.destroy();
    unsubscribe();
    unsubscribeValidation();
  }

  const flowEditor = Object.freeze({
    ...editor,
    state: {
      ...editor.state,
      activeStepId: readonly(activeStepId),
      newStepOpenIntent: readonly(newStepOpenIntent),
      validationErrors,
      saveStatus: unifiedSaveStatus,
      isPublished,
      canEditDataRetentionDays
    },
    setResource: editor.setResource,
    addStep,
    insertStepAfter,
    createDraftingChainStarter,
    assistantRevision,
    loadAssistant,
    saveAssistant,
    updateAssistantImmediately,
    listAssistantPrompts,
    selectStep,
    selectFirstStepIfUnselected,
    setName,
    setDescription,
    setDataRetentionDays,
    setDataRetentionDaysFromInput,
    replaceStepAtIndex,
    removeStepAtIndex,
    moveStepAtIndex,
    replaceFormSchemaFields,
    setTranscriptionEnabled,
    setWizardMetadata,
    applyStepsWithSafeOrderRemap,
    rewriteInputFieldVariableReferences,
    rewriteStepNameVariableReferences,
    flushFlowSaves,
    flushAssistantSaves,
    flushSaves,
    scheduleAutoSave,
    destroy
  });

  return flowEditor;
}

function initFlowEditor(data: FlowEditorInitData) {
  const flowEditor = createFlowEditor(data);
  setFlowEditor(flowEditor);
  return flowEditor;
}

type FlowEditor = ReturnType<typeof createFlowEditor>;

export {
  initFlowEditor,
  getFlowEditor,
  createFlowEditor,
  getFlowWizardMetadata,
  getUnifiedFlowSaveStatus
};
export type { FlowEditor, FlowMetadataJson, FlowWizardMetadata };
