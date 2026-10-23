import type { z } from "zod";

/**
 * What Eneo said about a call: who it is for (forwarded identity, for endpoints that require
 * it), where its signed file links point, and whether tool views are shown. All come from
 * headers on a request that already carries the deployment bearer, never from tool arguments.
 */
export type CallContext = {
  tenantId: string;
  userId: string;
  fileOrigin?: string;
  /** Eneo shows tool views to the reader, so a tool can say what the reader already sees. */
  showsViews?: boolean;
};

/** A file a tool produced, returned as a standard MCP embedded resource (base64 blob). */
export type EmbeddedFile = { uri: string; mimeType: string; blob: string };
/** An image a tool produced, returned as a standard MCP image block (base64). */
export type ImageBlock = { data: string; mimeType: string };

/** A tool result that carries files or images next to its structured data. */
export class RichResult {
  constructor(
    readonly structured: Record<string, unknown>,
    readonly files: EmbeddedFile[],
    readonly images: ImageBlock[] = [],
  ) {}
}

/**
 * An interactive view a tool brings (an MCP App): one HTML page the host shows with the
 * tool's call, in a sandboxed frame. `ui` is what the page declares about itself to the host
 * (border, browser permissions, network access); a page that names no network gets none.
 */
export type ToolView = { uri: string; html: string; ui?: Record<string, unknown> };

export type ToolDefinition = {
  name: string;
  title: string;
  description: string;
  inputSchema: z.ZodRawShape;
  readOnly: boolean;
  view?: ToolView;
  execute(raw: unknown, ctx: CallContext): Promise<Record<string, unknown> | RichResult>;
};
