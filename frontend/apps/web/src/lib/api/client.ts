import { createEneo } from "@eneo/eneo-js";
import { env } from "$env/dynamic/public";

/**
 * Unauthenticated eneo client for public endpoints like federation discovery.
 * Used in login flows before user authentication.
 */
export const eneo = createEneo({
  baseUrl: env.PUBLIC_ENEO_BACKEND_URL || ""
});
