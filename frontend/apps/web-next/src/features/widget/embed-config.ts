import { createWidgetClient, EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";

/** Availability and frame policy belong to the same server-issued document. */
export function isEmbedDocumentUnavailable(): boolean {
  return document.documentElement.dataset.eneoEmbedState === "unavailable";
}

/** Load visitor configuration directly from FastAPI, without browser-session cookies. */
export async function loadEmbedConfig(
  publicId: string,
  signal?: AbortSignal
): Promise<WidgetPublicConfig | null> {
  // A paused/unknown widget's freely framed notice cannot turn into an active
  // chat after reactivation. Only a new document can receive its active CSP.
  if (isEmbedDocumentUnavailable()) return null;
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
