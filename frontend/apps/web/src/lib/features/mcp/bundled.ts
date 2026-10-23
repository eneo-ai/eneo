/**
 * Servers built into Eneo (the bundled tool runtime). Their identity is Eneo's
 * own: shown in the UI language from the tool the row serves, never from the
 * row's stored name and description, which the backend seeds in English.
 */
import type { Globe } from "@lucide/svelte";
import { m } from "$lib/paraglide/messages";
import { getCapability } from "./capabilities";

/**
 * General (per-space) servers the runtime offers, by their tool key. Every
 * runtime tool is a function today; these entries only name rows added while
 * the tool was still a general server, which keep working until retired.
 */
export const BUNDLED_SERVERS: Record<
  string,
  { label: () => string; description: () => string; icon: typeof Globe }
> = {
  compute: {
    label: m.tools_bundled_compute,
    description: m.tools_bundled_compute_description,
    // The compute function's glyph, so the admin list and the chat agree.
    icon: getCapability("compute")!.icon
  },
  charts: {
    label: m.tools_bundled_charts,
    description: m.tools_bundled_charts_description,
    // The charts function's glyph, so the admin list and the chat agree.
    icon: getCapability("charts")!.icon
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
