import type { FlowStep } from "@eneo/eneo-js";
import type { FlowEditor } from "$lib/features/flows/FlowEditor";
import { SvelteMap, SvelteSet } from "svelte/reactivity";
import {
  buildFlowStepMcpCompatibilityMap,
  hasLoadedFlowStepMcpClassificationInputs
} from "$lib/features/flows/flowStepMcpConfig";

type SpaceMcpServer = {
  id: string;
  security_classification?: { security_level?: number; name?: string } | null;
};

/**
 * Loads every flow step's assistant into a revision-keyed map so MCP server
 * security compatibility can be computed across the whole flow, not just the
 * active step. Owns the concurrency gate that prevents an assistant from being
 * fetched twice while a load is in flight.
 */
export class FlowStepMcpState {
  #flowEditor: FlowEditor;

  assistantsById = new SvelteMap<string, unknown>();
  #lastLoadedRevisionByAssistant = new SvelteMap<string, number>();
  #loadingAssistantIds = new SvelteSet<string>();

  constructor(opts: { flowEditor: FlowEditor }) {
    this.#flowEditor = opts.flowEditor;
  }

  /**
   * Re-run whenever the assistant revision bumps: refresh the active
   * assistant's entry, then load any step assistant whose cached revision is
   * stale. `revision` is read from the store by the driving effect so this
   * method re-executes on every save.
   */
  syncAssistants(args: {
    revision: number;
    activeStep: FlowStep | null;
    steps: FlowStep[];
    activeAssistant: unknown;
    showMcpSection: boolean;
  }) {
    const { revision, activeStep, steps, activeAssistant, showMcpSection } = args;
    if (!showMcpSection) return;

    if (activeAssistant && activeStep?.assistant_id) {
      this.assistantsById.set(activeStep.assistant_id, activeAssistant);
      this.#lastLoadedRevisionByAssistant.set(activeStep.assistant_id, revision);
    }

    const assistantIds = steps
      .map((step) => step.assistant_id)
      .filter(
        (assistantId): assistantId is string =>
          typeof assistantId === "string" && assistantId.length > 0
      );

    for (const assistantId of assistantIds) {
      if (
        this.#lastLoadedRevisionByAssistant.get(assistantId) === revision ||
        this.#loadingAssistantIds.has(assistantId)
      ) {
        continue;
      }
      this.#loadingAssistantIds.add(assistantId);
      void this.#flowEditor
        .loadAssistant(assistantId)
        .then((assistant) => {
          this.assistantsById.set(assistantId, assistant);
          this.#lastLoadedRevisionByAssistant.set(assistantId, revision);
        })
        .finally(() => {
          this.#loadingAssistantIds.delete(assistantId);
        });
    }
  }

  /** Per-server security compatibility for the active step's MCP selection. */
  getCompatibilityById(args: {
    activeStep: FlowStep | null;
    steps: FlowStep[];
    showMcpSection: boolean;
    availableServers: SpaceMcpServer[];
    spaceSecurityClassification: { security_level?: number } | null | undefined;
    reasonWhenIncompatible: string;
  }): Record<string, { isCompatible: boolean; requiredLevel: number | null; reason?: string }> {
    const {
      activeStep,
      steps,
      showMcpSection,
      availableServers,
      spaceSecurityClassification,
      reasonWhenIncompatible
    } = args;
    if (!activeStep || !showMcpSection) {
      return {};
    }
    const compatibilityMap = buildFlowStepMcpCompatibilityMap({
      step: activeStep,
      steps,
      assistantsById: this.assistantsById,
      availableServers,
      spaceSecurityClassification
    });
    return Object.fromEntries(
      Object.entries(compatibilityMap).map(([serverId, compatibility]) => [
        serverId,
        {
          ...compatibility,
          reason: compatibility.isCompatible ? undefined : reasonWhenIncompatible
        }
      ])
    );
  }

  /** True once every assistant feeding the active step's security floor is loaded. */
  isCompatibilityReady(args: { activeStep: FlowStep | null; steps: FlowStep[] }): boolean {
    return hasLoadedFlowStepMcpClassificationInputs({
      step: args.activeStep,
      steps: args.steps,
      assistantsById: this.assistantsById
    });
  }
}
