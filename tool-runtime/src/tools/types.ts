import type { z } from "zod";

/**
 * What Eneo said about a call: who it is for (forwarded identity, for endpoints that require
 * it) and where its signed file links point. Both come from headers on a request that already
 * carries the deployment bearer, never from tool arguments.
 */
export type CallContext = { tenantId: string; userId: string; fileOrigin?: string };

/** A file a tool produced, returned as a standard MCP embedded resource (base64 blob). */
export type EmbeddedFile = { uri: string; mimeType: string; blob: string };

/** A tool result that carries files next to its structured data. */
export class RichResult {
  constructor(
    readonly structured: Record<string, unknown>,
    readonly files: EmbeddedFile[],
  ) {}
}

export type ToolDefinition = {
  name: string;
  title: string;
  description: string;
  inputSchema: z.ZodRawShape;
  readOnly: boolean;
  execute(raw: unknown, ctx: CallContext): Promise<Record<string, unknown> | RichResult>;
};
