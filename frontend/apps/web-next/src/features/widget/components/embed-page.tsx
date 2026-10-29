"use client";

import { createWidgetClient, EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { readPreviewToken } from "../preview";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import { EmbedApp } from "./embed-app";
import { WidgetNotice } from "./widget-unavailable";

type Scheme = "light" | "dark" | "auto";

/**
 * The client side of the embed page: the chat for a configuration the
 * server loaded, the notice for a widget that is not available, or, for the
 * admin page's live preview of a draft, the configuration fetched here with
 * the token from the URL fragment (which never reaches a server log).
 */
export function EmbedPage({
  config: loaded,
  unavailable,
  publicId,
  hostOrigin,
  hostScheme,
  preview
}: {
  config: WidgetPublicConfig | null;
  unavailable: boolean;
  publicId: string;
  hostOrigin: string | null;
  hostScheme: Scheme | null;
  preview: boolean;
}) {
  const t = useTranslations();
  // The fragment exists in the browser only; before hydration the page shows
  // that it is loading, and without a token afterwards that it cannot.
  const hydrated = useHydrated();
  const wantsPreview = preview && !loaded && !unavailable;
  const previewToken = useMemo(
    () => (wantsPreview && hydrated ? readPreviewToken(location.hash) : null),
    [wantsPreview, hydrated]
  );
  const [previewConfig, setPreviewConfig] = useState<WidgetPublicConfig | null>(null);
  const [fetchFailed, setFetchFailed] = useState(false);
  const previewFailed = fetchFailed || (wantsPreview && hydrated && previewToken === null);

  useEffect(() => {
    if (!previewToken) return;
    // The public config is cacheable for a minute; a preview must always
    // show what was just saved.
    const client = createWidgetClient({
      baseUrl: location.origin,
      publicId,
      getToken: () => previewToken,
      fetch: (input, init) => fetch(input, { ...init, cache: "no-store", credentials: "omit" })
    });
    let cancelled = false;
    client
      .config()
      .then((fetched) => {
        if (!cancelled) setPreviewConfig(fetched);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setFetchFailed(true);
        if (!(error instanceof EneoError)) console.error(error);
      });
    return () => {
      cancelled = true;
    };
  }, [previewToken, publicId]);

  const config = loaded ?? previewConfig;
  if (config) {
    return (
      <EmbedApp
        config={config}
        publicId={publicId}
        hostOrigin={hostOrigin}
        hostScheme={hostScheme}
        previewToken={previewToken}
      />
    );
  }
  if (unavailable) return <WidgetNotice hostOrigin={hostOrigin} />;
  return (
    <main className="bg-ax-surface text-ax-text-secondary fixed inset-0 flex items-center justify-center p-6">
      {previewFailed ? (
        <p className="text-center text-sm" role="alert">
          {t("widget_preview_unavailable")}
        </p>
      ) : (
        <p className="text-sm">{t("widget_preview_loading")}</p>
      )}
    </main>
  );
}
