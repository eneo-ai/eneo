import type { Schema } from "./api/models";

let current: Schema<"WebRuntimeConfig"> | undefined;

export async function loadRuntimeConfig(): Promise<Schema<"WebRuntimeConfig">> {
  const response = await fetch("/api/v1/runtime-config", {
    credentials: "same-origin",
    cache: "no-store"
  });
  if (!response.ok) throw new Error(`Runtime config request failed (${response.status})`);
  return response.json();
}

export function setRuntimeConfig(config: Schema<"WebRuntimeConfig">): void {
  current = config;
}

export function runtimeConfig(): Schema<"WebRuntimeConfig"> {
  if (!current) throw new Error("Runtime config is unavailable before boot");
  return current;
}
