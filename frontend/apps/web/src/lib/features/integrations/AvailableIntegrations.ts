import { getContext, setContext } from "svelte";
import { writable, type Writable } from "svelte/store";
import type { UserIntegration } from "@intric/intric-js";

const key = Symbol("Integrations context");

export function setAvailableIntegrations(value: UserIntegration[]): void {
  let store = getContextStore();
  if (store) {
    store.set(value);
  } else {
    setContext(key, writable(value));
  }
}

export function getAvailableIntegrations(): Writable<UserIntegration[]> {
  return getContextStore();
}

function getContextStore(): Writable<UserIntegration[]> {
  return getContext<Writable<UserIntegration[]>>(key);
}
