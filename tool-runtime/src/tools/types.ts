import type { z } from "zod";

/** Who a call is for, from Eneo's forwarded identity headers (endpoints that require it). */
export type CallContext = { tenantId: string; userId: string };

export type ToolDefinition = {
  name: string;
  title: string;
  description: string;
  inputSchema: z.ZodRawShape;
  readOnly: boolean;
  execute(raw: unknown, ctx: CallContext): Promise<Record<string, unknown>>;
};
