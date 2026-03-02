/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { createContext } from "$lib/core/context";
import { writable, type Writable } from "svelte/store";
import { browser } from "$app/environment";

type FlowUserMode = "user" | "power_user";

const STORAGE_KEY = "eneo:flow-user-mode";

const [getFlowUserMode, setFlowUserMode] = createContext<Writable<FlowUserMode>>(
  "Flow user mode toggle"
);

function initFlowUserMode(): Writable<FlowUserMode> {
  let initial: FlowUserMode = "user";
  if (browser) {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "user" || stored === "power_user") {
      initial = stored;
    }
  }

  const mode = writable<FlowUserMode>(initial);

  if (browser) {
    mode.subscribe(($mode) => {
      localStorage.setItem(STORAGE_KEY, $mode);
    });
  }

  setFlowUserMode(mode);
  return mode;
}

export { initFlowUserMode, getFlowUserMode, type FlowUserMode };
