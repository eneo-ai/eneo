/**
 * Servers built into Eneo (the bundled tool runtime). Their identity is Eneo's
 * own: shown in the UI language from the tool the row serves, never from the
 * row's stored name and description, which the backend seeds in English.
 */
import { Calculator, ChartColumn, type Globe } from "@lucide/svelte";
import { m } from "$lib/paraglide/messages";
import { getCapability } from "./capabilities";

/** The general (per-space) servers the runtime offers, by their tool key. */
export const BUNDLED_SERVERS: Record<
  string,
  { label: () => string; description: () => string; icon: typeof Globe }
> = {
  compute: {
    label: m.tools_bundled_compute,
    description: m.tools_bundled_compute_description,
    icon: Calculator
  },
  charts: {
    label: m.tools_bundled_charts,
    description: m.tools_bundled_charts_description,
    icon: ChartColumn
  }
};

export const bundledServerLabel = (tool: string): string => BUNDLED_SERVERS[tool]?.label() ?? tool;

type ServerLike = { http_auth_type: string; http_url: string; purpose?: string | null };

/** The runtime tool a bundled row serves (the last segment of its URL), or null. */
export function bundledToolOf(server: ServerLike): string | null {
  if (server.http_auth_type !== "bundled") return null;
  const tool = server.http_url.replace(/\/+$/, "").split("/").pop();
  return tool || null;
}

/**
 * Localized name and description of a bundled row: a capability provider is
 * named after its function, a general server after its tool. Null for every
 * other server, whose own name and description are shown.
 */
export function bundledIdentity(server: ServerLike): { name: string; description: string } | null {
  const tool = bundledToolOf(server);
  if (tool === null) return null;
  const capability = getCapability(server.purpose);
  if (capability) {
    return { name: capability.label(), description: capability.bundledDescription?.() ?? "" };
  }
  const general = BUNDLED_SERVERS[tool];
  return general ? { name: general.label(), description: general.description() } : null;
}
