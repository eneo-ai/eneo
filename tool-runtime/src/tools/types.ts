import type { z } from "zod";

/**
 * What Eneo said about a call: who it is for (forwarded identity, for endpoints that require
 * it) and where its signed file links point. Both come from headers on a request that already
 * carries the deployment bearer, never from tool arguments.
 */
export type CallContext = { tenantId: string; userId: string; fileOrigin?: string };

export type ToolDefinition = {
  name: string;
  title: string;
  description: string;
  inputSchema: z.ZodRawShape;
  readOnly: boolean;
  execute(raw: unknown, ctx: CallContext): Promise<Record<string, unknown>>;
};
