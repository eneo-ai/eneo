/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import type { Flow, FlowSparse, Intric } from "@intric/intric-js";
import { get, writable } from "svelte/store";

const [getFlowsManager, setFlowsManager] = createContext<ReturnType<typeof FlowsManager>>(
  "Manages flows"
);

type FlowsManagerParams = {
  flows: FlowSparse[];
  spaceId: string;
  intric: Intric;
};

function initFlowsManager(data: FlowsManagerParams) {
  const manager = FlowsManager(data);
  setFlowsManager(manager);
  return manager;
}

function FlowsManager(data: FlowsManagerParams) {
  const { intric } = data;

  const flows = writable<FlowSparse[]>(data.flows);
  const spaceId = writable(data.spaceId);

  async function refreshFlows() {
    try {
      const $spaceId = get(spaceId);
      const result = await intric.flows.list({ spaceId: $spaceId });
      const items = result.items ?? result;
      flows.set(items as FlowSparse[]);
      return items;
    } catch (e) {
      console.error("Error fetching flows", e);
    }
  }

  async function createFlow(name: string): Promise<Flow> {
    const $spaceId = get(spaceId);
    const created = await intric.flows.create({ spaceId: $spaceId, name, steps: [] });
    await refreshFlows();
    return created as Flow;
  }

  async function deleteFlow(flowId: string) {
    await intric.flows.delete({ id: flowId });
    await refreshFlows();
  }

  return Object.freeze({
    state: {
      flows,
      spaceId
    },
    refreshFlows,
    createFlow,
    deleteFlow
  });
}

export { initFlowsManager, getFlowsManager };
