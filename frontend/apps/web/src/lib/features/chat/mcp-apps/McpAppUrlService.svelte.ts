import { browser } from "$app/environment";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import { getEneo } from "$lib/core/Eneo";
import type { Eneo } from "@eneo/eneo-js";
import { SvelteMap } from "svelte/reactivity";

/** Re-mint this long before the token actually expires. */
const EXPIRY_MARGIN_MS = 60 * 1000;

type ViewUrlRecord = {
  url: string | undefined;
  html: string;
  expiresAt: number;
  /** Human-readable mint failure (e.g. content origin not configured). */
  error: string | undefined;
};

/**
 * Signed-URL cache for MCP App views, mirroring AttachmentUrlService: a
 * synchronous getter for templates that kicks off the mint on first access
 * and re-mints when a cached URL nears expiry.
 */
class McpAppUrlService {
  #eneo: Eneo;
  #viewUrls = new SvelteMap<string, ViewUrlRecord>();
  #queuedViews = new Set<string>();

  constructor({ eneo = getEneo() }: { eneo: Eneo }) {
    this.#eneo = eneo;
  }

  get(viewId: string): ViewUrlRecord | undefined {
    if (!browser || !viewId) return undefined;
    const record = this.#viewUrls.get(viewId);
    if (record && (record.error !== undefined || Date.now() < record.expiresAt)) {
      return record;
    }
    if (!this.#queuedViews.has(viewId)) {
      this.#queuedViews.add(viewId);
      this.#mint(viewId);
    }
    return undefined;
  }

  async #mint(viewId: string) {
    try {
      const { url, expires_at, html } = await this.#eneo.mcpApps.mintViewToken({ viewId });
      this.#viewUrls.set(viewId, {
        url,
        html,
        expiresAt: expires_at * 1000 - EXPIRY_MARGIN_MS,
        error: undefined
      });
    } catch (error) {
      this.#viewUrls.set(viewId, {
        url: undefined,
        html: "",
        expiresAt: Number.MAX_SAFE_INTEGER,
        error: error instanceof Error ? error.message : String(error)
      });
    } finally {
      this.#queuedViews.delete(viewId);
    }
  }
}

export const [getMcpAppUrlService, initMcpAppUrlService] = createClassContext(
  "MCP App URL Service",
  McpAppUrlService
);
