/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import { createResourceEditor } from "$lib/core/editing/ResourceEditor";
import {
  IntricError,
  type Flow,
  type FlowStep,
  type Intric,
  type PromptSparse
} from "@intric/intric-js";
import { derived, get, writable } from "svelte/store";
import { uid } from "uid";
import { shouldSaveAssistantImmediately } from "./assistantSavePolicy";
import { remapStepOrderTemplateTokens, replaceExactTemplateToken } from "./flowVariableTokens";
import { getFlowStepValidationIssues, mapOutputToInputType } from "./flowStepTypes";

const [getFlowEditor, setFlowEditor] =
  createContext<ReturnType<typeof initFlowEditor>>("Edit a flow");

function initFlowEditor(data: { flow: Flow; intric: Intric; onUpdateDone?: (flow: Flow) => void }) {
  type LoadedAssistant = Awaited<ReturnType<typeof data.intric.flows.assistants.get>>;
  const editor = createResourceEditor({
    intric: data.intric,
    resource: data.flow,
    defaults: {},
    updateResource: async (resource, changes) => {
      // Strip temp IDs before sending to API
      const cleanChanges = { ...changes } as Record<string, unknown>;
      if (cleanChanges.steps && Array.isArray(cleanChanges.steps)) {
        cleanChanges.steps = (cleanChanges.steps as FlowStep[]).map((step) => ({
          ...step,
          id: step.id?.startsWith?.("_temp_") ? undefined : step.id
        }));
      }
      const updated = (await data.intric.flows.update({
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
        "mcp_policy",
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

  // Derived: is the flow published?
  const isPublished = derived(editor.state.resource, ($resource) => {
    return $resource.published_version != null;
  });

  // Assistant cache for step inspector
  const assistantCache = new Map<string, unknown>();
  const assistantSaveStatus = writable<"idle" | "pending" | "saving" | "error">("idle");
  const assistantErrorPrefix = "assistant:";
  const flowErrorPrefix = "flow:";
  const typedIOValidationPrefix = `${flowErrorPrefix}typed-io:`;

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
    return issues;
  }

  function getFlowId(): string {
    return get(editor.state.resource).id;
  }

  async function loadAssistant(assistantId: string): Promise<LoadedAssistant | null> {
    if (!assistantId || assistantId === "") return null;

    // Wait for any in-flight save to land in the cache first
    if (assistantSavePromises.has(assistantId)) {
      await assistantSavePromises.get(assistantId)!.catch(() => {});
    }

    let base = (assistantCache.get(assistantId) as LoadedAssistant) ?? null;
    if (!base) {
      try {
        base = await data.intric.flows.assistants.get({
          id: getFlowId(),
          assistantId
        });
        assistantCache.set(assistantId, base);
      } catch {
        return null;
      }
    }

    // Overlay any pending unsaved changes so the caller sees the latest state
    const pending = pendingAssistantChanges.get(assistantId);
    if (pending && base) {
      return { ...base, ...pending } as LoadedAssistant;
    }
    return base;
  }

  async function updateAssistantImmediately(
    assistantId: string,
    changes: Record<string, unknown>
  ): Promise<void> {
    if (!assistantId || assistantId === "") return;
    assistantSaveStatus.set("saving");
    setAssistantValidationError(assistantId, null);
    try {
      const updated = await data.intric.flows.assistants.update({
        id: getFlowId(),
        assistantId,
        update: changes
      });
      assistantCache.set(assistantId, updated);
      assistantSaveStatus.set("idle");
      setAssistantValidationError(assistantId, null);
    } catch (error) {
      assistantSaveStatus.set("error");
      const message =
        error instanceof IntricError
          ? error.getReadableMessage()
          : "Failed to update flow step assistant";
      setAssistantValidationError(assistantId, message);
      throw error;
    }
  }

  let legacyTemplateCleanupStarted = false;
  async function cleanupLegacyMirroredInputTemplates(): Promise<void> {
    if (legacyTemplateCleanupStarted) return;
    if (get(isPublished)) return;
    legacyTemplateCleanupStarted = true;

    const currentSteps = [...(get(editor.state.update).steps ?? [])];
    if (currentSteps.length === 0) return;

    let changed = false;
    const nextSteps = [...currentSteps];
    for (let index = 0; index < currentSteps.length; index += 1) {
      const step = currentSteps[index] as FlowStep;
      const bindings = (step.input_bindings ?? {}) as Record<string, unknown>;
      const question = typeof bindings.question === "string" ? bindings.question.trim() : "";
      if (question.length === 0) continue;
      if (!step.assistant_id || step.assistant_id === "") continue;

      const assistant = await loadAssistant(step.assistant_id);
      if (!assistant || typeof assistant !== "object") continue;
      const promptText =
        typeof (assistant as { prompt?: { text?: unknown } }).prompt?.text === "string"
          ? (assistant as { prompt: { text: string } }).prompt.text.trim()
          : "";
      if (promptText.length === 0) continue;
      if (question !== promptText) continue;

      const nextBindings: Record<string, unknown> = { ...bindings };
      delete nextBindings.question;
      delete nextBindings.text;
      nextSteps[index] = {
        ...step,
        input_bindings: Object.keys(nextBindings).length > 0 ? nextBindings : null
      };
      changed = true;
    }

    if (!changed) return;
    editor.state.update.update((resource) => ({
      ...resource,
      steps: nextSteps
    }));
    scheduleAutoSave();
  }

  const pendingAssistantChanges = new Map<string, Record<string, unknown>>();
  const assistantSaveTimers = new Map<string, ReturnType<typeof setTimeout>>();
  const assistantSaveInFlight = new Set<string>();
  const assistantSavePromises = new Map<string, Promise<void>>();

  function clearAssistantSaveTimer(assistantId: string) {
    const existingTimer = assistantSaveTimers.get(assistantId);
    if (existingTimer) {
      clearTimeout(existingTimer);
      assistantSaveTimers.delete(assistantId);
    }
  }

  function refreshAssistantSaveStatus() {
    if (assistantSaveInFlight.size > 0) {
      assistantSaveStatus.set("saving");
      return;
    }
    if (assistantSaveTimers.size > 0 || pendingAssistantChanges.size > 0) {
      assistantSaveStatus.set("pending");
      return;
    }
    if (get(assistantSaveStatus) !== "error") {
      assistantSaveStatus.set("idle");
    }
  }

  async function runAssistantSaveNow(assistantId: string): Promise<void> {
    if (!assistantId || assistantId === "") return;
    if (assistantSaveInFlight.has(assistantId)) {
      await assistantSavePromises.get(assistantId);
      return;
    }
    const merged = pendingAssistantChanges.get(assistantId);
    if (!merged) return;

    pendingAssistantChanges.delete(assistantId);
    assistantSaveInFlight.add(assistantId);
    assistantSaveStatus.set("saving");

    const savePromise = (async () => {
      try {
        const updated = await data.intric.flows.assistants.update({
          id: getFlowId(),
          assistantId,
          update: merged
        });
        assistantCache.set(assistantId, updated);
        setAssistantValidationError(assistantId, null);
      } catch (e) {
        const queued = pendingAssistantChanges.get(assistantId) ?? {};
        pendingAssistantChanges.set(assistantId, { ...merged, ...queued });
        assistantSaveStatus.set("error");
        const msg =
          e instanceof IntricError ? e.getReadableMessage() : "Failed to save step configuration";
        setAssistantValidationError(assistantId, msg);
        throw e;
      } finally {
        assistantSaveInFlight.delete(assistantId);
        assistantSavePromises.delete(assistantId);
        refreshAssistantSaveStatus();
      }
    })();

    assistantSavePromises.set(assistantId, savePromise);
    await savePromise;
    if (pendingAssistantChanges.has(assistantId)) {
      queueAssistantSave(assistantId, 0);
    }
  }

  function queueAssistantSave(assistantId: string, delayMs = 500) {
    clearAssistantSaveTimer(assistantId);
    const timer = setTimeout(() => {
      assistantSaveTimers.delete(assistantId);
      void runAssistantSaveNow(assistantId).catch(() => {
        // Validation/UI status is updated in runAssistantSaveNow.
      });
    }, delayMs);
    assistantSaveTimers.set(assistantId, timer);
    refreshAssistantSaveStatus();
  }

  async function saveAssistant(assistantId: string, changes: Record<string, unknown>) {
    if (!assistantId || assistantId === "") return;
    const current = pendingAssistantChanges.get(assistantId) ?? {};
    const merged = { ...current, ...changes };
    pendingAssistantChanges.set(assistantId, merged);
    setAssistantValidationError(assistantId, null);
    if (get(assistantSaveStatus) === "error") {
      assistantSaveStatus.set("pending");
    }
    if (shouldSaveAssistantImmediately(changes)) {
      clearAssistantSaveTimer(assistantId);
      await runAssistantSaveNow(assistantId);
      return;
    }
    queueAssistantSave(assistantId);
  }

  async function flushAssistantSaves(): Promise<void> {
    let guard = 0;
    while (guard < 25) {
      guard += 1;
      const ids = new Set<string>([
        ...assistantSaveTimers.keys(),
        ...pendingAssistantChanges.keys(),
        ...assistantSavePromises.keys()
      ]);
      if (ids.size === 0) {
        refreshAssistantSaveStatus();
        return;
      }
      for (const assistantId of ids) {
        clearAssistantSaveTimer(assistantId);
      }
      const results = await Promise.allSettled(
        [...ids].map((assistantId) => runAssistantSaveNow(assistantId))
      );
      const rejected = results.find((result) => result.status === "rejected");
      if (rejected && rejected.status === "rejected") {
        throw rejected.reason;
      }
    }
    throw new Error("Assistant save flush exceeded retry guard.");
  }

  // Unified save status combining flow + assistant saves
  const unifiedSaveStatus = derived([saveStatus, assistantSaveStatus], ([$flow, $assistant]) => {
    if ($assistant === "saving" || $flow === "saving") {
      return "saving" as const;
    }
    if ($assistant === "error") return "unsaved" as const;
    if ($flow === "unsaved") return "unsaved" as const;
    return "saved" as const;
  });

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

  /** Instant step creation — no dialogs */
  async function addStep(): Promise<void> {
    const $update = get(editor.state.update);
    const currentSteps = $update.steps ?? [];
    const stepCount = currentSteps.length;
    const isFirst = stepCount === 0;
    const prevStep = stepCount > 0 ? currentSteps[stepCount - 1] : null;

    const tempId = `_temp_${uid(12)}`;
    const defaultStepName = `Nytt steg ${stepCount + 1}`;
    const newStep: Partial<FlowStep> & { id: string } = {
      id: tempId,
      assistant_id: "",
      step_order: stepCount + 1,
      user_description: defaultStepName,
      input_source: isFirst ? "flow_input" : "previous_step",
      input_type: isFirst ? "text" : mapOutputToInputType((prevStep as FlowStep)?.output_type),
      output_mode: "pass_through",
      output_type: "text",
      mcp_policy: "inherit"
    };

    // Instant UI update
    editor.state.update.update((u) => ({
      ...u,
      steps: [...(u.steps ?? []), newStep as FlowStep]
    }));
    activeStepId.set(tempId);

    // Background: create hidden assistant
    try {
      const assistant = await data.intric.flows.assistants.create({
        id: getFlowId(),
        name: defaultStepName
      });
      // Wire the real assistant_id
      editor.state.update.update((u) => ({
        ...u,
        steps: (u.steps ?? []).map((s: FlowStep) =>
          s.id === tempId ? { ...s, assistant_id: assistant.id } : s
        )
      }));
      assistantCache.set(assistant.id, assistant);
    } catch {
      // Remove the step if assistant creation fails
      editor.state.update.update((u) => ({
        ...u,
        steps: (u.steps ?? []).filter((s: FlowStep) => s.id !== tempId)
      }));
      activeStepId.set(null);
    }
  }

  /** Insert step after a given step order */
  async function insertStepAfter(afterOrder: number): Promise<void> {
    const $update = get(editor.state.update);
    const currentSteps = [...($update.steps ?? [])];

    const tempId = `_temp_${uid(12)}`;
    const prevStep = currentSteps.find((s: FlowStep) => s.step_order === afterOrder);
    const isFirstInsert = afterOrder === 0;

    const defaultStepName = `Nytt steg ${afterOrder + 1}`;
    const newStep: Partial<FlowStep> & { id: string } = {
      id: tempId,
      assistant_id: "",
      step_order: afterOrder + 1,
      user_description: defaultStepName,
      input_source: isFirstInsert ? "flow_input" : "previous_step",
      input_type: isFirstInsert
        ? "text"
        : mapOutputToInputType((prevStep as FlowStep)?.output_type),
      output_mode: "pass_through",
      output_type: "text",
      mcp_policy: "inherit"
    };

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
      const assistant = await data.intric.flows.assistants.create({
        id: getFlowId(),
        name: defaultStepName
      });
      editor.state.update.update((u) => ({
        ...u,
        steps: (u.steps ?? []).map((s: FlowStep) =>
          s.id === tempId ? { ...s, assistant_id: assistant.id } : s
        )
      }));
      assistantCache.set(assistant.id, assistant);
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
    }
  }

  async function createTemplateFillStarter(): Promise<void> {
    await addStep();
    let steps = [...(get(editor.state.update).steps ?? [])];
    const factStep = steps[steps.length - 1];
    if (factStep) {
      factStep.user_description = "Extrahera fakta";
      if (factStep.assistant_id) {
        await updateAssistantImmediately(factStep.assistant_id, {
          name: factStep.user_description
        });
      }
    }
    editor.state.update.update((resource) => ({ ...resource, steps }));

    await addStep();
    steps = [...(get(editor.state.update).steps ?? [])];
    const sectionStep = steps[steps.length - 1];
    if (sectionStep) {
      sectionStep.user_description = "Bakgrund";
      if (sectionStep.assistant_id) {
        await updateAssistantImmediately(sectionStep.assistant_id, {
          name: sectionStep.user_description
        });
      }
    }
    editor.state.update.update((resource) => ({ ...resource, steps }));

    await addStep();
    steps = [...(get(editor.state.update).steps ?? [])];
    const assemblyStep = steps[steps.length - 1];
    if (assemblyStep) {
      assemblyStep.user_description = "Sammanställ dokument";
      assemblyStep.input_source = "previous_step";
      assemblyStep.input_type = "text";
      assemblyStep.output_type = "docx";
      assemblyStep.output_mode = "template_fill";
      assemblyStep.output_config = {
        placeholders: [],
        bindings: {}
      };
      if (assemblyStep.assistant_id) {
        await updateAssistantImmediately(assemblyStep.assistant_id, {
          name: assemblyStep.user_description
        });
      }
      activeStepId.set(assemblyStep.id ?? null);
    }
    editor.state.update.update((resource) => ({ ...resource, steps }));
    scheduleAutoSave();
  }

  async function listAssistantPrompts(assistantId: string): Promise<PromptSparse[]> {
    return data.intric.assistants.listPrompts({ id: assistantId });
  }

  function getStableStepKey(step: FlowStep, index: number): string {
    if (step.id && !step.id.startsWith("_temp_")) return `id:${step.id}`;
    if (step.assistant_id) return `assistant:${step.assistant_id}`;
    return `index:${index}`;
  }

  async function applyStepsWithSafeOrderRemap(nextSteps: FlowStep[]): Promise<void> {
    const previousSteps = [...(get(editor.state.update).steps ?? [])];
    const previousOrderByKey = new Map<string, number>();
    for (let i = 0; i < previousSteps.length; i += 1) {
      const step = previousSteps[i];
      previousOrderByKey.set(getStableStepKey(step, i), step.step_order);
    }

    const remapByOldOrder = new Map<number, number>();
    const seenOldOrders = new Set<number>();
    const rewrittenSteps = nextSteps.map((step, index) => {
      const key = getStableStepKey(step, index);
      const oldOrder = previousOrderByKey.get(key);
      if (oldOrder !== undefined) {
        remapByOldOrder.set(oldOrder, step.step_order);
        seenOldOrders.add(oldOrder);
      }
      return { ...step };
    });

    const deletedOrders = new Set<number>();
    for (const previousStep of previousSteps) {
      if (!seenOldOrders.has(previousStep.step_order)) {
        deletedOrders.add(previousStep.step_order);
      }
    }

    const impactedDeletedReferences = new Set<number>();
    for (let i = 0; i < rewrittenSteps.length; i += 1) {
      const step = rewrittenSteps[i];
      const bindings = (step.input_bindings as Record<string, unknown> | null | undefined) ?? null;
      const question = typeof bindings?.question === "string" ? bindings.question : null;
      if (question) {
        const remapped = remapStepOrderTemplateTokens(question, remapByOldOrder, deletedOrders);
        if (remapped.changed) {
          rewrittenSteps[i] = {
            ...step,
            input_bindings: {
              ...(bindings ?? {}),
              question: remapped.text
            }
          };
        }
        for (const deletedReference of remapped.rewrittenDeletedReferences) {
          impactedDeletedReferences.add(deletedReference);
        }
      }
    }

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
    const toToken = newName.trim();
    if (!fromToken || !toToken || fromToken === toToken) return 0;

    let rewrittenCount = 0;
    const steps = get(editor.state.update).steps ?? [];
    for (const step of steps) {
      if (!step.assistant_id) continue;
      const assistant = await loadAssistant(step.assistant_id);
      if (!assistant || typeof assistant !== "object") continue;

      const prompt = (assistant as { prompt?: { text?: unknown; description?: unknown } }).prompt;
      const currentText = typeof prompt?.text === "string" ? prompt.text : "";
      const nextText = replaceExactTemplateToken(currentText, fromToken, toToken);
      if (nextText !== currentText) {
        const nextPrompt = {
          text: nextText,
          description: typeof prompt?.description === "string" ? prompt.description : ""
        };
        await updateAssistantImmediately(step.assistant_id, { prompt: nextPrompt });
        rewrittenCount += 1;
      }
    }

    const nextSteps = steps.map((step) => {
      const bindings = (step.input_bindings as Record<string, unknown> | null | undefined) ?? null;
      const question = typeof bindings?.question === "string" ? bindings.question : null;
      if (!question) return step;
      const rewritten = replaceExactTemplateToken(question, fromToken, toToken);
      if (rewritten === question) return step;
      return {
        ...step,
        input_bindings: { ...(bindings ?? {}), question: rewritten }
      };
    });
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
    const nextSteps = allSteps.map((step) => {
      if (step.step_order <= renamedStepOrder) return step;
      const bindings = (step.input_bindings as Record<string, unknown> | null | undefined) ?? null;
      const question = typeof bindings?.question === "string" ? bindings.question : null;
      if (!question) return step;
      const rewritten = replaceExactTemplateToken(question, fromToken, toToken);
      if (rewritten === question) return step;
      return {
        ...step,
        input_bindings: { ...(bindings ?? {}), question: rewritten }
      };
    });
    editor.state.update.update((resource) => ({ ...resource, steps: nextSteps }));
    scheduleAutoSave();

    return rewrittenCount;
  }

  function destroy() {
    clearAutoSaveTimer();
    for (const timer of assistantSaveTimers.values()) {
      clearTimeout(timer);
    }
    assistantSaveTimers.clear();
    void flushAssistantSaves().catch(() => {
      // Best-effort flush during teardown.
    });
    unsubscribe();
    unsubscribeValidation();
  }

  const flowEditor = Object.freeze({
    ...editor,
    state: {
      ...editor.state,
      activeStepId,
      validationErrors,
      saveStatus: unifiedSaveStatus,
      isPublished
    },
    setResource: editor.setResource,
    addStep,
    insertStepAfter,
    createTemplateFillStarter,
    loadAssistant,
    saveAssistant,
    updateAssistantImmediately,
    listAssistantPrompts,
    applyStepsWithSafeOrderRemap,
    rewriteInputFieldVariableReferences,
    rewriteStepNameVariableReferences,
    flushAssistantSaves,
    scheduleAutoSave,
    destroy
  });

  void cleanupLegacyMirroredInputTemplates();
  setFlowEditor(flowEditor);
  return flowEditor;
}

export { initFlowEditor, getFlowEditor };
