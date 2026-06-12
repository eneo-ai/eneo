"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { INTEGRATION_CALLBACK_MESSAGE_TYPE } from "@/features/integrations/callback-message";

type View = { status: "processing" | "done" | "error"; errorMessage?: string };

/** Posts the OAuth params to the opener and closes; returns what to render. */
function runHandoff(): View {
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

export function CallbackHandoff() {
  const t = useTranslations();
  const [view, setView] = useState<View>({ status: "processing" });

  useEffect(() => {
    const result = runHandoff();
    // Deferred: the params only exist in the browser, so the first render is
    // always "processing" and the real view lands a microtask later.
    let cancelled = false;
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
