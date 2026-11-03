import { useSearchParams } from "@/lib/navigation";
import { EmbedPage } from "./components/embed-page";
import { WidgetNotice } from "./components/widget-unavailable";
import type { WidgetPublicConfig } from "@eneo/eneo-js";
import { PREVIEW_QUERY } from "./preview";

/** Preserve the loader's public query parameters while typing preview reload dependencies. */
export function embedSearch(search: Record<string, unknown>) {
  const text = (key: string) => (typeof search[key] === "string" ? search[key] : undefined);
  return {
    preview: text(PREVIEW_QUERY),
    origin: text("origin"),
    scheme: text("scheme"),
    mode: text("mode")
  };
}

/** Only an exact origin may become the postMessage peer. */
export function parseHostOrigin(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.origin === raw ? url.origin : null;
  } catch {
    return null;
  }
}

export function parseScheme(raw: string | null): "light" | "dark" | "auto" | null {
  return raw === "light" || raw === "dark" || raw === "auto" ? raw : null;
}

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
