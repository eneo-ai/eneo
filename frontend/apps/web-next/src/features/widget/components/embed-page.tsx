import { createWidgetClient, EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";
import { useTranslations } from "use-intl";
import { useEffect, useState } from "react";
import { readPreviewToken } from "../preview";
import { EmbedApp } from "./embed-app";
import { WidgetNotice } from "./widget-unavailable";

type Scheme = "light" | "dark" | "auto";

/** Load visitor configuration directly from FastAPI, without browser-session cookies. */
export async function loadEmbedConfig(
  publicId: string,
  signal?: AbortSignal
): Promise<WidgetPublicConfig | null> {
  const timeout = AbortSignal.timeout(8000);
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const client = createWidgetClient({
    baseUrl: location.origin,
    publicId,
    fetch: (input, init) =>
      fetch(input, { ...init, signal: requestSignal, credentials: "omit", cache: "no-store" })
  });
  try {
    return await client.config();
  } catch (error) {
    if (error instanceof EneoError && error.status === 404) return null;
    throw error;
  }
}

/** The token for a draft stays in the browser's URL fragment. */
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
  const previewToken = preview ? readPreviewToken(location.hash) : null;
  const [previewConfig, setPreviewConfig] = useState<WidgetPublicConfig | null>(null);
  const [fetchFailed, setFetchFailed] = useState(false);

  useEffect(() => {
    if (!previewToken) return;
    const controller = new AbortController();
    const client = createWidgetClient({
      baseUrl: location.origin,
      publicId,
      getToken: () => previewToken,
      fetch: (input, init) =>
        fetch(input, {
          ...init,
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]),
          cache: "no-store",
          credentials: "omit"
        })
    });
    void client
      .config()
      .then((config) => {
        if (!controller.signal.aborted) setPreviewConfig(config);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFetchFailed(true);
      });
    return () => controller.abort();
  }, [previewToken, publicId]);

  const config = loaded ?? previewConfig;
  if (config)
    return (
      <EmbedApp
        config={config}
        publicId={publicId}
        hostOrigin={hostOrigin}
        hostScheme={hostScheme}
        previewToken={previewToken}
      />
    );
  if (unavailable || fetchFailed || (preview && !previewToken))
    return <WidgetNotice hostOrigin={hostOrigin} />;
  return (
    <main className="bg-ax-surface text-ax-text-secondary fixed inset-0 flex items-center justify-center p-6">
      <p className="text-sm">{t("widget_preview_loading")}</p>
    </main>
  );
}
