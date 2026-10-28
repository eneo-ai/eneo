import createClient, { type Client } from "openapi-fetch";
import { API_BASE, onBrowserApiResponse } from "./base";
import type { paths } from "./schema";

/** A typed Eneo API client, regardless of transport (direct or proxied). */
export type EneoClient = Client<paths>;

/**
 * Typed client for client components. Paths keep their full /api/v1/...
 * shape under API_BASE (base.ts), which also owns what a refusal does.
 */
export const browserApi: EneoClient = createClient<paths>({ baseUrl: API_BASE });

browserApi.use({ onResponse: onBrowserApiResponse });
