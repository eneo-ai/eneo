import { browser } from "$app/environment";
import { getEneo } from "$lib/core/Eneo";
import type { Eneo } from "@eneo/eneo-js";
import { getContext, onDestroy, onMount, setContext } from "svelte";
import { SvelteSet } from "svelte/reactivity";

/**
 * Drives the popup through which a user authorizes Eneo at an OAuth MCP
 * server. The backend owns the OAuth state (PKCE, issuer, scope); this class
 * only opens the vendor's authorization page, receives the code the callback
 * route posts back, and completes the authorization through the API.
 *
 * `connectAll` runs several servers through one popup window in sequence:
 * after each callback the same window navigates to the next authorization
 * URL, so the browser's popup blocker is asked once.
 *
 * The callback route is `/mcp-oauth/callback`; it posts a
 * `eneo/mcp-oauth-callback` message to the opener and closes itself.
 */

export type McpOAuthConnection = Awaited<ReturnType<Eneo["mcpOauth"]["myConnections"]>>[number];

export type McpOAuthConnectResult =
  { success: true; connection: McpOAuthConnection } | { success: false; error: Error };

type CallbackMessage = {
  type: "eneo/mcp-oauth-callback";
  code: string | null;
  state: string | null;
  iss: string | null;
  error: string | null;
  error_description: string | null;
};

const MESSAGE_TYPE = "eneo/mcp-oauth-callback";
const POPUP_WIDTH = 600;
const POPUP_HEIGHT = 760;

function isCallbackMessage(data: unknown): data is CallbackMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    (data as { type: unknown }).type === MESSAGE_TYPE
  );
}

export class McpOAuthConnectService {
  #eneo: Eneo;
  #popup: Window | null = null;
  #popupWatcher: ReturnType<typeof setInterval> | null = null;
  /** The authorization in flight: resolved by the callback message carrying its state. */
  #pending: {
    state: string;
    resolve: (message: CallbackMessage) => void;
    reject: (error: Error) => void;
  } | null = null;
  #listeners = new SvelteSet<(serverId: string, result: McpOAuthConnectResult) => void>();
  /** Servers being connected right now, for buttons to disable themselves. */
  connecting = new SvelteSet<string>();

  constructor(eneo?: Eneo) {
    this.#eneo = eneo ?? getEneo();
    if (browser) window.addEventListener("message", this.#onMessage);
  }

  /** Called with every finished attempt, whichever component started it. */
  subscribe(listener: (serverId: string, result: McpOAuthConnectResult) => void) {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  isConnecting(serverId: string) {
    return this.connecting.has(serverId);
  }

  /** Authorize Eneo at one server through a popup. */
  async connect(serverId: string): Promise<McpOAuthConnectResult> {
    const results = await this.connectAll([serverId]);
    return results[0];
  }

  /** Authorize Eneo at several servers in turn, through one popup window. */
  async connectAll(serverIds: string[]): Promise<McpOAuthConnectResult[]> {
    if (!browser) throw new Error("Can only connect from a browser");
    const results: McpOAuthConnectResult[] = [];
    this.#markConnecting(serverIds, true);
    // Open the window synchronously, on the user's click, or Safari blocks it.
    this.#openPopup();
    try {
      for (const serverId of serverIds) {
        const result = await this.#connectOne(serverId);
        results.push(result);
        for (const listener of this.#listeners) listener(serverId, result);
        if (!result.success && this.#popup?.closed !== false) break;
      }
    } finally {
      this.#closePopup();
      this.#markConnecting(serverIds, false);
    }
    return results;
  }

  destroy() {
    if (!browser) return;
    window.removeEventListener("message", this.#onMessage);
    this.#closePopup();
    this.#pending?.reject(new Error("cancelled"));
    this.#pending = null;
  }

  async #connectOne(serverId: string): Promise<McpOAuthConnectResult> {
    try {
      const { url, state } = await this.#eneo.mcpOauth.authorizeUrl({ id: serverId });
      if (!this.#popup || this.#popup.closed) {
        throw new Error("popup_blocked");
      }
      const callback = new Promise<CallbackMessage>((resolve, reject) => {
        this.#pending = { state, resolve, reject };
      });
      this.#popup.location.href = url;
      const message = await callback;
      if (message.error || !message.code) {
        throw new Error(message.error_description || message.error || "authorization_denied");
      }
      const connection = await this.#eneo.mcpOauth.completeCallback({
        id: serverId,
        code: message.code,
        state,
        iss: message.iss
      });
      return { success: true, connection };
    } catch (e) {
      return { success: false, error: e instanceof Error ? e : new Error(String(e)) };
    } finally {
      this.#pending = null;
    }
  }

  #onMessage = (event: MessageEvent) => {
    // The callback route only ever posts to its own origin.
    if (event.origin !== window.location.origin) return;
    if (!isCallbackMessage(event.data)) return;
    const pending = this.#pending;
    if (!pending || event.data.state !== pending.state) return;
    pending.resolve(event.data);
  };

  #openPopup() {
    const width = Math.min(POPUP_WIDTH, window.innerWidth);
    const height = Math.min(POPUP_HEIGHT, window.innerHeight);
    const left = (window.innerWidth - width) / 2 + window.screenX;
    const top = (window.innerHeight - height) / 2 + window.screenY;
    this.#popup = window.open(
      "about:blank",
      "eneo-mcp-oauth",
      `width=${width},height=${height},top=${top},left=${left},popup`
    );
    this.#popupWatcher = setInterval(() => {
      if (this.#popup && this.#popup.closed) {
        // The user closed the vendor's page: the pending authorization is over.
        this.#pending?.reject(new Error("popup_closed"));
        this.#pending = null;
        this.#closePopup();
      }
    }, 500);
  }

  #closePopup() {
    if (this.#popupWatcher) clearInterval(this.#popupWatcher);
    this.#popupWatcher = null;
    if (this.#popup && !this.#popup.closed) this.#popup.close();
    this.#popup = null;
  }

  #markConnecting(serverIds: string[], on: boolean) {
    for (const id of serverIds) {
      if (on) this.connecting.add(id);
      else this.connecting.delete(id);
    }
  }
}

const contextKey = Symbol("MCP OAuth connect");

/** One service per conversation view, shared by the connect chip and the tool steps. */
export function initMcpOAuthConnect(): McpOAuthConnectService {
  const service = new McpOAuthConnectService();
  onDestroy(() => service.destroy());
  return setContext(contextKey, service);
}

export function getMcpOAuthConnect(): McpOAuthConnectService | undefined {
  return getContext<McpOAuthConnectService | undefined>(contextKey);
}

/** A service for a page of its own (the account page), torn down with it. */
export function useMcpOAuthConnect(): McpOAuthConnectService {
  const service = new McpOAuthConnectService();
  onMount(() => () => service.destroy());
  return service;
}
