import { createIntric } from "@intric/intric-js";
import { env } from "$env/dynamic/public";

/**
 * Unauthenticated intric client for public endpoints like federation discovery.
 * Used in login flows before user authentication.
 */
export const intric = createIntric({
  baseUrl: env.PUBLIC_INTRIC_BACKEND_URL || "",
});
