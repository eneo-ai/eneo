import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { PublicPage } from "@/features/auth/public-page";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { replaceUrl } from "@/lib/navigation";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import { INTEGRATION_CALLBACK_MESSAGE_TYPE } from "@/features/integrations/callback-message";
import { SHAREPOINT_OAUTH_STATE_KEY } from "@/features/admin/integrations/integrations";

type View =
  | { status: "processing" | "popup_done" }
  | { status: "connected"; email: string | null }
  | { status: "error"; errorMessage?: string };

/** Popup OAuth: posts the params to the opener and closes; returns what to render. */
function runPopupHandoff(url: URL): View {
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
  return { status: "popup_done" };
}

/** Full-page service-account return; the backend validates and consumes matching state. */
async function completeServiceAccount(
  url: URL,
  stored: string,
  t: ReturnType<typeof useTranslations>
): Promise<View> {
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  let parsed: unknown;
  try {
    parsed = JSON.parse(stored);
  } catch {
    parsed = null;
  }
  const expectedState =
    parsed && typeof parsed === "object" && "state" in parsed && typeof parsed.state === "string"
      ? parsed.state
      : null;
  if (!state || !expectedState || state !== expectedState)
    return { status: "error", errorMessage: t("sharepoint_callback_state_invalid") };
  if (!code) return { status: "error", errorMessage: t("sharepoint_callback_code_missing") };

  sessionStorage.removeItem(SHAREPOINT_OAUTH_STATE_KEY);
  try {
    const config = await unwrap(
      browserApi.POST("/api/v1/admin/sharepoint/service-account/auth/callback", {
        body: { auth_code: code, state }
      })
    );
    return { status: "connected", email: config.service_account_email ?? null };
  } catch (error) {
    return { status: "error", errorMessage: getErrorMessage(error, t) };
  }
}

export function CallbackHandoff({
  accessibilityStatementUrl = null
}: {
  accessibilityStatementUrl?: string | null;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const [view, setView] = useState<View>({ status: "processing" });
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void Promise.resolve().then(async () => {
      try {
        // A popup belongs to its opener, even if it inherited a stored state
        // from a separate full-page service-account sign-in.
        const url = new URL(window.location.href);
        if (window.opener) {
          setView(runPopupHandoff(url));
          return;
        }
        // The result page stays open; consume captured parameters without keeping
        // the authorization code in the current history entry.
        replaceUrl(url.pathname + url.hash);
        if (url.searchParams.has("error")) {
          setView(runPopupHandoff(url));
          return;
        }
        let stored: string | null;
        try {
          stored = sessionStorage.getItem(SHAREPOINT_OAUTH_STATE_KEY);
        } catch {
          setView({ status: "error", errorMessage: t("sharepoint_callback_storage_unavailable") });
          return;
        }
        setView(
          stored
            ? await completeServiceAccount(url, stored, t)
            : { status: "error", errorMessage: t("sharepoint_callback_state_invalid") }
        );
      } catch (error) {
        setView({ status: "error", errorMessage: getErrorMessage(error, t) });
      }
    });
  }, [t]);

  useEffect(() => {
    if (view.status === "connected")
      announce(`${t("service_account_configured")} ${view.email ?? ""}`);
    else if (view.status === "error" && !window.opener)
      announce(view.errorMessage ?? t("integration_callback_unexpected_error"));
  }, [announce, t, view]);

  const title =
    view.status === "error"
      ? t("authentication_failed")
      : view.status === "connected"
        ? t("service_account_configured")
        : t("integration_callback_finishing_sign_in");
  const showBack = !window.opener && (view.status === "error" || view.status === "connected");
  return (
    <PublicPage
      title={title}
      accessibilityStatementUrl={accessibilityStatementUrl}
      footer={
        showBack ? (
          <Button
            label={t("back_to_integrations")}
            href="/admin/integrations"
            variant="secondary"
          />
        ) : undefined
      }
    >
      {view.status === "error" ? (
        <p className="text-ax-text-secondary break-words">
          {view.errorMessage ?? t("integration_callback_unexpected_error")}
        </p>
      ) : view.status === "connected" ? (
        view.email ? (
          <p className="break-words">
            {t("connected_as")}: <strong>{view.email}</strong>
          </p>
        ) : (
          <p>{t("connection_successful")}</p>
        )
      ) : (
        <p className="text-ax-text-secondary">{t("integration_callback_close_window")}</p>
      )}
    </PublicPage>
  );
}
