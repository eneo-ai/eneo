import type { Client } from "openapi-fetch";
import { browserApi } from "@/lib/api/browser";
import type { FlowPaths } from "./types";

/**
 * The browser client narrowed to the flow routes. The routes are not in the
 * generated schema yet (see `types.ts`); the cast goes when `gen:api` has
 * picked them up, and every call site then types against `paths` as usual.
 */
export const flowsApi = browserApi as unknown as Client<FlowPaths>;
