import { useSearchParams } from "@/lib/navigation";
import { EmbedPage } from "./components/embed-page";
import { WidgetNotice } from "./components/widget-unavailable";
import type { WidgetPublicConfig } from "@eneo/eneo-js";
import { PREVIEW_QUERY } from "./preview";
import { parseHostOrigin, parseScheme } from "./urls";

export function EmbedRoute({
  publicId,
  config
}: {
  publicId: string;
  config: WidgetPublicConfig | null;
}) {
  const query = useSearchParams();
  const preview = query.get(PREVIEW_QUERY) === "1";
  return (
    <EmbedPage
      config={config}
      unavailable={!preview && !config}
      publicId={publicId}
      hostOrigin={query.get("mode") === "full" ? null : parseHostOrigin(query.get("origin"))}
      hostScheme={parseScheme(query.get("scheme"))}
      preview={preview}
    />
  );
}

/** Network failures still complete the loader handshake with a reachable close control. */
export function EmbedError() {
  const query = useSearchParams();
  return (
    <WidgetNotice
      hostOrigin={query.get("mode") === "full" ? null : parseHostOrigin(query.get("origin"))}
    />
  );
}
