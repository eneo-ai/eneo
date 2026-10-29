"use client";

import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { INTEGRATION_CALLBACK_MESSAGE_TYPE } from "@/features/integrations/callback-message";
import { SHAREPOINT_OAUTH_STATE_KEY } from "@/features/admin/integrations/integrations";
import { navigateTo } from "@/lib/navigate-to";

type View = { status: "processing" | "done" | "error"; errorMessage?: string };

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

  sessionStorage.removeItem(SHAREPOINT_OAUTH_STATE_KEY);
  try {
    await unwrap(
      browserApi.POST("/api/v1/admin/sharepoint/service-account/auth/callback", {
        body: { auth_code: code, state }
      })
    );
    navigateTo("/admin/integrations", { replace: true });
    return { status: "done" };
  } catch (error) {
    return { status: "error", errorMessage: error instanceof Error ? error.message : undefined };
  }
}

export function CallbackHandoff() {
  const t = useTranslations();
  const [view, setView] = useState<View>({ status: "processing" });
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void Promise.resolve().then(async () => {
      try {
        // A popup belongs to its opener, even if it inherited a stored state
        // from a separate full-page service-account sign-in.
        if (window.opener || new URL(window.location.href).searchParams.has("error")) {
          setView(runPopupHandoff());
          return;
        }
        const stored = sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY);
        setView((stored && (await completeServiceAccount(stored))) || { status: "error" });
      } catch {
        setView({ status: "error" });
      }
    });
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
