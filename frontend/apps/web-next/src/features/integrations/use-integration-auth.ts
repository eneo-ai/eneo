"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { isIntegrationCallbackMessage } from "./callback-message";

type UserIntegration = Schema<"UserIntegration">;

export type ConnectResult =
  | { success: true; integration: UserIntegration }
  | { success: false; error: Error };

type AuthRequest = {
  integration: UserIntegration;
  popup: Window | null;
  watcher: ReturnType<typeof setInterval>;
};

function popupAttributes() {
  const width = Math.min(700, window.innerWidth);
  const height = Math.min(900, window.innerHeight);
  const left = (window.innerWidth - width) / 2 + window.screenX;
  const top = (window.innerHeight - height) / 2 + window.screenY;
  return `width=${width},height=${height},top=${top},left=${left},popup`;
}

/**
 * OAuth connect flow for external integrations, ported from the Svelte
 * IntegrationAuthService: opens a centered popup (about:blank FIRST — Safari
 * blocks popups opened after an await), points it at the backend-issued auth
 * URL with state=tenant_integration_id, and listens for the callback page's
 * postMessage to register the auth code.
 */
export function useIntegrationAuth(onConnected: (result: ConnectResult) => void): {
  connect: (integration: UserIntegration) => Promise<void>;
  isConnecting: (integration: UserIntegration) => boolean;
} {
  const t = useTranslations();
  const requestsRef = useRef(new Map<string, AuthRequest>());
  const onConnectedRef = useRef(onConnected);
  const [connectingIds, setConnectingIds] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    onConnectedRef.current = onConnected;
  });

  const finishRequest = useCallback((tenantIntegrationId: string) => {
    const request = requestsRef.current.get(tenantIntegrationId);
    if (request) {
      request.popup?.close();
      clearInterval(request.watcher);
      requestsRef.current.delete(tenantIntegrationId);
    }
    setConnectingIds(new Set(requestsRef.current.keys()));
  }, []);

  useEffect(() => {
    const requests = requestsRef.current;

    async function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      if (!isIntegrationCallbackMessage(event.data)) return;

      const { code, state: tenantIntegrationId } = event.data;
      if (!code || !tenantIntegrationId) {
        toast.warning(t("integration_callback_missing_required_fields"));
        return;
      }

      const request = requests.get(tenantIntegrationId);
      if (!request) {
        toast.error(t("integration_callback_unexpected_error"));
        return;
      }
      finishRequest(tenantIntegrationId);

      try {
        const updated = await unwrap(
          browserApi.POST("/api/v1/integrations/auth/callback/token/", {
            body: { auth_code: code, tenant_integration_id: tenantIntegrationId }
          })
        );
        onConnectedRef.current({ success: true, integration: updated });
      } catch (error) {
        onConnectedRef.current({
          success: false,
          error: error instanceof Error ? error : new Error(String(error))
        });
      }
    }

    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
      for (const request of requests.values()) {
        request.popup?.close();
        clearInterval(request.watcher);
      }
      requests.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only listener; callbacks go through refs
  }, []);

  const connect = useCallback(
    async (integration: UserIntegration) => {
      const tenantIntegrationId = integration.tenant_integration_id;
      if (requestsRef.current.has(tenantIntegrationId)) return;

      const popup = window.open("about:blank", `popup_${tenantIntegrationId}`, popupAttributes());
      if (!popup) {
        toast.error(t("integration_callback_unexpected_error"));
        return;
      }

      const watcher = setInterval(() => {
        if (popup.closed) finishRequest(tenantIntegrationId);
      }, 1000);
      requestsRef.current.set(tenantIntegrationId, { integration, popup, watcher });
      setConnectingIds(new Set(requestsRef.current.keys()));

      try {
        const { auth_url } = await unwrap(
          browserApi.GET("/api/v1/integrations/auth/{tenant_integration_id}/url/", {
            params: {
              path: { tenant_integration_id: tenantIntegrationId },
              query: { state: tenantIntegrationId }
            }
          })
        );
        popup.location.href = auth_url;
      } catch (error) {
        finishRequest(tenantIntegrationId);
        onConnectedRef.current({
          success: false,
          error: error instanceof Error ? error : new Error(String(error))
        });
      }
    },
    [finishRequest, t]
  );

  const isConnecting = useCallback(
    (integration: UserIntegration) => connectingIds.has(integration.tenant_integration_id),
    [connectingIds]
  );

  return { connect, isConnecting };
}
