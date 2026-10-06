"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { INTEGRATION_CALLBACK_MESSAGE_TYPE } from "@/features/integrations/callback-message";

type View = { status: "processing" | "done" | "error"; errorMessage?: string };

const OAUTH_STATE_KEY = "sharepoint_service_account_oauth";

/** Popup OAuth: posts the params to the opener and closes; returns what to render. */
function runPopupHandoff(): View {
  const url = new URL(window.location.href);
  const error = url.searchParams.get("error");
  if (error) {
    return { status: "error", errorMessage: url.searchParams.get("error_description") ?? error };
  }

  const opener = window.opener as Window | null;
  if (!opener) return { status: "error" };

  opener.postMessage(
    {
      type: INTEGRATION_CALLBACK_MESSAGE_TYPE,
      code: url.searchParams.get("code"),
      state: url.searchParams.get("state"),
      params: url.search
    },
    window.location.origin
  );
  window.close();
  return { status: "done" };
}

/**
 * Full-page SharePoint service-account OAuth return: the admin dialog stored a
 * state token and did a top-level redirect (no opener). Complete the auth
 * server-side via the proxy, then return to admin integrations.
 */
async function completeServiceAccount(stored: string): Promise<View | null> {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  let expectedState: string | undefined;
  try {
    expectedState = (JSON.parse(stored) as { state?: string }).state;
  } catch {
    expectedState = undefined;
  }
  if (!code || !state || state !== expectedState) return null;

  sessionStorage.removeItem(OAUTH_STATE_KEY);
  try {
    await unwrap(
      browserApi.POST("/api/v1/admin/sharepoint/service-account/auth/callback", {
        body: { auth_code: code, state }
      })
    );
    window.location.href = "/admin/integrations";
    return { status: "done" };
  } catch (error) {
    return { status: "error", errorMessage: error instanceof Error ? error.message : undefined };
  }
}

export function CallbackHandoff() {
  const t = useTranslations();
  const [view, setView] = useState<View>({ status: "processing" });

  useEffect(() => {
    let cancelled = false;
    const stored = sessionStorage.getItem(OAUTH_STATE_KEY);

    if (stored) {
      void completeServiceAccount(stored).then((result) => {
        if (!cancelled) setView(result ?? runPopupHandoff());
      });
      return () => {
        cancelled = true;
      };
    }

    const result = runPopupHandoff();
    queueMicrotask(() => {
      if (!cancelled) setView(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-2 p-8 text-center">
      {view.status === "error" ? (
        <>
          <h1 className="text-xl font-semibold">{t("authentication_failed")}</h1>
          <p className="text-muted-foreground max-w-md">
            {view.errorMessage ?? t("integration_callback_unexpected_error")}
          </p>
        </>
      ) : (
        <>
          <h1 className="text-xl font-semibold">{t("integration_callback_finishing_sign_in")}</h1>
          <p className="text-muted-foreground">{t("integration_callback_close_window")}</p>
        </>
      )}
    </main>
  );
}
