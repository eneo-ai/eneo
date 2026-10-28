import { createWidgetClient, EneoError, type WidgetPublicConfig } from "@eneo/eneo-js";
import { env } from "@/lib/env";

/** The backend did not answer within the deadline. */
export class BackendTimeout extends Error {
  constructor() {
    super("The backend did not answer in time");
    this.name = "BackendTimeout";
  }
}

/** The loader stops waiting after three seconds; answer before it does. */
export const RESPONSE_DEADLINE_MS = 2500;

/**
 * The public configuration of an active widget, straight from the backend
 * (never cached: a pause or unpublish must reach the next page view). Null
 * for a paused, archived or unknown widget; a timeout and any other failure
 * throw.
 */
export async function fetchPublicConfig(
  publicId: string,
  { timeoutMs = RESPONSE_DEADLINE_MS }: { timeoutMs?: number } = {}
): Promise<WidgetPublicConfig | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const client = createWidgetClient({
    baseUrl: env.ENEO_BACKEND_URL,
    publicId,
    fetch: (input, init) => fetch(input, { ...init, cache: "no-store", signal: controller.signal })
  });
  try {
    return await client.config();
  } catch (error) {
    if (controller.signal.aborted) throw new BackendTimeout();
    if (error instanceof EneoError && error.status === 404) return null;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
