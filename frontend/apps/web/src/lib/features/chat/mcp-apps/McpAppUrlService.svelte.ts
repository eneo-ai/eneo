import { browser } from "$app/environment";
import { createClassContext } from "$lib/core/helpers/createClassContext";
import { getEneo } from "$lib/core/Eneo";
import { EneoError, type Eneo } from "@eneo/eneo-js";
import { SvelteMap } from "svelte/reactivity";

/** Re-mint this long before the token actually expires. */
const EXPIRY_MARGIN_MS = 60 * 1000;

/** Why a view link could not be minted. */
export type ViewUrlError = {
  message: string;
  /** The backend refuses every view until an administrator sets the content origin. */
  contentOriginMissing: boolean;
};

type ViewUrlRecord = {
  url: string | undefined;
  html: string;
  expiresAt: number;
  error: ViewUrlError | undefined;
};

const CONTENT_ORIGIN_MISSING_STATUS = 424;

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
      const message = error instanceof Error ? error.message : String(error);
      console.warn(`MCP app view ${viewId} could not be linked: ${message}`);
      this.#viewUrls.set(viewId, {
        url: undefined,
        html: "",
        expiresAt: Number.MAX_SAFE_INTEGER,
        error: {
          message,
          contentOriginMissing:
            error instanceof EneoError && error.status === CONTENT_ORIGIN_MISSING_STATUS
        }
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
