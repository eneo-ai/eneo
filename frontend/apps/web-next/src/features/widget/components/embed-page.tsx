import { createWidgetClient, type WidgetPublicConfig } from "@eneo/eneo-js";
import { useTranslations } from "use-intl";
import { useEffect, useId, useState } from "react";
import { isEmbedDocumentUnavailable } from "../embed-config";
import { readPreviewToken } from "../preview";
import { EmbedApp } from "./embed-app";
import { WidgetNotice } from "./widget-unavailable";

type Scheme = "light" | "dark" | "auto";

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
  const loadingId = useId();
  const documentUnavailable = isEmbedDocumentUnavailable();
  const previewToken = preview ? readPreviewToken(location.hash) : null;
  const [previewConfig, setPreviewConfig] = useState<WidgetPublicConfig | null>(null);
  const [fetchFailed, setFetchFailed] = useState(false);

  useEffect(() => {
    if (!previewToken || documentUnavailable) return;
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
  }, [previewToken, publicId, documentUnavailable]);

  if (documentUnavailable) return <WidgetNotice hostOrigin={hostOrigin} />;
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
    <main
      aria-labelledby={loadingId}
      className="bg-ax-surface text-ax-text-secondary fixed inset-0 flex items-center justify-center p-6"
    >
      <p id={loadingId} className="text-sm">
        {t("widget_preview_loading")}
      </p>
    </main>
  );
}
