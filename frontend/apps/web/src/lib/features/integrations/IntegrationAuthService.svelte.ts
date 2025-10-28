import { browser } from "$app/environment";
import { getIntric } from "$lib/core/Intric";
import type { Intric, UserIntegration } from "@intric/intric-js";
import { onMount } from "svelte";
import { SvelteMap } from "svelte/reactivity";

/**
 * Service for handling OAuth authentication flows for external integrations.
 * Manages popup windows and message communication for the authentication process.
 *
 * @param {Object} options
 * @param {OnConnectedCallback} options.onConnected - Callback function to handle all
 *        integration connection results (both success and failure cases)
 *
 * **Important**: You need to `destroy()` the class instance after you're done to properly
 * remove event handlers from the window and prevent memory leaks.
 *
 * @example
 * const authService = new IntegrationAuthService((result) => {
 *   if (result.success) {
 *     // ... result.integration is available
 *   } else {
 *     // ... result.error has the error
 *   }
 * });
 *
 * // Connect an integration
 * await authService.connect(integration);
 *
 * // Clean up when done
 * authService.destroy();
 */
export class IntegrationAuthService {
  /** Stores the current auth requests, key is the `tenant_integration_id` */
  #authRequests = new SvelteMap<string, AuthRequestContext>();
  #onConnected: OnConnectedCallback;
  #intric: Intric;

  constructor(options: { onConnected: OnConnectedCallback }) {
    this.#onConnected = options.onConnected;
    this.#intric = getIntric();
    onMount(() => {
      window.addEventListener("message", this.receiveMessageHandler);
    });
  }

  /**
   * Initiates the connection process for an integration by opening a popup window
   * for authentication.
   *
   * @param {UserIntegration} integration - The integration to connect
   * @param {OnConnectedCallback} callback - Function to handle the connection result.
   *        See {@link OnConnectedCallback} for usage example and type details.
   * @throws {Error} If called outside of a browser environment
   * @throws {Error} If there's already an active connection attempt for this integration
   */
  async connect(integration: UserIntegration) {
    if (!browser) {
      throw new Error("Can only connect to external connection inside browser");
    }

    const tenant_integration_id = integration.tenant_integration_id!;
    if (this.#authRequests.has(tenant_integration_id)) {
      throw new Error(
        "You're already trying to connect this integration. Please cancel or finish your previous attempt."
      );
    }

    const { top, left, width, height } = this.#calculatePopupAttributes();

    // We need to open the popup immediately; if we try to await the auth url first, safari will block the popup
    let popup = window.open(
      "about:blank",
      `popup_${tenant_integration_id}}`,
      `width=${width},height=${height},top=${top},left=${left},popup`
    );

    const url = await this.#intric.integrations.user.getAuthUrl({
      integration: { tenant_integration_id },
      state: tenant_integration_id
    });

    if (popup) {
      popup.location = url;
    } else {
      throw new Error("Could not open authentication popup. Please allow popups for this page.");
    }

    // Keep track of popup in case the user closes the popup window
    const popupInspectInterval = setInterval(() => {
      if (!popup || popup.closed) {
        popup = null;
        clearInterval(popupInspectInterval);
        this.#authRequests.delete(tenant_integration_id);
      }
    }, 1000);

    this.#authRequests.set(integration.tenant_integration_id!, {
      popup,
      popupInspectInterval,
      integration
    });
  }

  // Position popup in center of current window
  #calculatePopupAttributes() {
    const innerW = window.innerWidth;
    const innerH = window.innerHeight;
    // Popup dimensions
    const width = Math.min(700, innerW);
    const height = Math.min(900, innerH);
    // Calculate the center position
    const left = (innerW - width) / 2 + window.screenX;
    const top = (innerH - height) / 2 + window.screenY;
    return { top, left, width, height };
  }

  receiveMessageHandler = async (event: MessageEvent) => {
    const { origin, data } = event;
    const allowedOrigins = ["https://integrations.intric.ai"];
    if (browser) {
      allowedOrigins.push(window.location.origin);
    }
    if (!allowedOrigins.includes(origin)) return;
    if (!isIntegrationCallbackMessage(data)) return;

    const { code, state: integrationId } = data;

    // code and id are required
    if (!code || !integrationId) {
      const missing = [];
      if (!code) missing.push("code");
      if (!integrationId) missing.push("state");
      alert(`Missing required fields: ${missing.join(", ")}`);
      return;
    }

    // Find and validate request
    const request = this.#authRequests.get(integrationId);
    if (!request) {
      alert(`No auth request found for state ${integrationId}`);
      return;
    }

    request.popup?.close();
    clearInterval(request.popupInspectInterval);

    try {
      const updatedIntegration = await this.#intric.integrations.user.registerAuthCode({
        integration: request.integration,
        code
      });
      this.#onConnected({ success: true, integration: updatedIntegration });
    } catch (e) {
      const error = e instanceof Error ? e : new Error(String(e));
      this.#onConnected({ success: false, error });
    } finally {
      this.#authRequests.delete(integrationId);
    }
  };

  /**
   * Checks if an integration is currently in the process of connecting.
   *
   * @param {UserIntegration} integration - The integration to check
   * @returns {boolean} True if there's an active connection attempt for this integration
   */
  isConnecting(integration: UserIntegration) {
    return this.#authRequests.has(integration.tenant_integration_id!);
  }

  destroy() {
    if (!browser) {
      return;
    }
    window.removeEventListener("message", this.receiveMessageHandler);
    this.#authRequests.forEach((request) => {
      request.popup?.close();
      request.popup = null;
      clearInterval(request.popupInspectInterval);
    });
  }
}

export type OnConnectedCallback = (
  result: { success: true; integration: UserIntegration } | { success: false; error: Error }
) => Promise<void> | void;

type AuthRequestContext = {
  integration: UserIntegration;
  popup: ReturnType<Window["open"]> | null;
  popupInspectInterval: ReturnType<typeof setInterval>;
};

type IntegrationCallbackMessage = {
  type: "intric/integration-callback";
  code: string | null;
  state: string | null;
  params: string;
};

function isIntegrationCallbackMessage(data: unknown): data is IntegrationCallbackMessage {
  if (data == null) return false;
  if (typeof data !== "object") return false;
  if (!("type" in data)) return false;

  return data && typeof data === "object" && data.type === "intric/integration-callback";
}
