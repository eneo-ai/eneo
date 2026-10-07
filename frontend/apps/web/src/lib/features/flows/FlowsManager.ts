/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import type { Flow, FlowSparse, Eneo } from "@eneo/eneo-js";
import { get, writable } from "svelte/store";
import { loadFlowList } from "./flowListLoader";

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
  const refreshError = writable<Error | null>(null);
  const refreshing = writable(false);
  let latestRefresh = 0;

  async function refreshFlows() {
    const request = ++latestRefresh;
    refreshing.set(true);
    try {
      const $spaceId = get(spaceId);
      const items = await loadFlowList(eneo, $spaceId);
      if (request === latestRefresh) {
        flows.set(items);
        refreshError.set(null);
      }
    } catch (cause) {
      // A completed create/delete/import stays successful when its subsequent read fails.
      if (request === latestRefresh) {
        refreshError.set(new Error("The flow list could not be refreshed.", { cause }));
      }
    } finally {
      if (request === latestRefresh) refreshing.set(false);
    }
  }

  async function createFlow(name: string): Promise<Flow> {
    const $spaceId = get(spaceId);
    const created = await eneo.flows.create({ spaceId: $spaceId, name, steps: [] });
    await refreshFlows();
    return created;
  }

  async function deleteFlow(flowId: string) {
    await eneo.flows.delete({ id: flowId });
    await refreshFlows();
  }

  return Object.freeze({
    state: {
      flows,
      spaceId,
      refreshError,
      refreshing
    },
    refreshFlows,
    createFlow,
    deleteFlow
  });
}

export { initFlowsManager, getFlowsManager };
