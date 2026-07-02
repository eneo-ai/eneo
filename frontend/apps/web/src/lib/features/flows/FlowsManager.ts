/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import type { Flow, FlowSparse, Eneo } from "@eneo/eneo-js";
import { get, writable } from "svelte/store";

const [getFlowsManager, setFlowsManager] =
  createContext<ReturnType<typeof FlowsManager>>("Manages flows");

type FlowsManagerParams = {
  flows: FlowSparse[];
  spaceId: string;
  eneo: Eneo;
};

function initFlowsManager(data: FlowsManagerParams) {
  const manager = FlowsManager(data);
  setFlowsManager(manager);
  return manager;
}

function FlowsManager(data: FlowsManagerParams) {
  const { eneo } = data;

  const flows = writable<FlowSparse[]>(data.flows);
  const spaceId = writable(data.spaceId);

  async function refreshFlows() {
    try {
      const $spaceId = get(spaceId);
      const result = await eneo.flows.list({ spaceId: $spaceId });
      const items = result.items ?? result;
      flows.set(items as FlowSparse[]);
      return items;
    } catch (e) {
      console.error("Error fetching flows", e);
    }
  }

  async function createFlow(name: string): Promise<Flow> {
    const $spaceId = get(spaceId);
    const created = await eneo.flows.create({ spaceId: $spaceId, name, steps: [] });
    await refreshFlows();
    return created as Flow;
  }

  async function deleteFlow(flowId: string) {
    await eneo.flows.delete({ id: flowId });
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
