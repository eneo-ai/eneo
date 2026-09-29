import { timingSafeEqual, createHash } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { publicError, ToolError } from "./errors";
import { RichResult, type CallContext, type ToolDefinition } from "./tools/types";

const VERSION = process.env.APP_VERSION ?? "0.0.0-dev";
const MAX_BODY_BYTES = 256 * 1024;
const MAX_RESULT_BYTES = 512 * 1024;
// Files a tool returns; matches Eneo's default MCP_TOOL_FILE_MAX_BYTES for one result.
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const BODY_TIMEOUT_MS = 10_000;

export type Endpoint = {
  slug: string;
  tools: ToolDefinition[];
  /** Upper bound for one tool call, including downloads and sandbox children. */
  toolTimeoutMs: number;
  /**
   * Tools that keep per-user state need Eneo's forwarded tenant and user ids (the server's
   * "forward identity" setting). Listing tools works without them.
   */
  requiresIdentity?: boolean;
};
export type ServerOptions = {
  token: string;
  maxConcurrency: number;
  endpoints: Endpoint[];
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** An exact HTTP(S) origin, or undefined for anything else (paths, credentials, junk). */
export function parseOrigin(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    const origin = value.replace(/\/$/, "");
    return ["http:", "https:"].includes(url.protocol) && url.origin === origin ? origin : undefined;
  } catch {
    return undefined;
  }
}

function callContext(request: Request, endpoint: Endpoint): CallContext {
  const tenantId = request.headers.get("x-eneo-tenant-id") ?? "";
  const userId = request.headers.get("x-eneo-user-id") ?? "";
  const fileOrigin = parseOrigin(request.headers.get("x-eneo-file-origin"));
  const origin = fileOrigin ? { fileOrigin } : {};
  if (UUID.test(tenantId) && UUID.test(userId)) return { tenantId, userId, ...origin };
  if (endpoint.requiresIdentity)
    throw new ToolError(
      "IDENTITY_REQUIRED",
      "This tool needs Eneo's tenant and user identity. Enable identity forwarding on the server in Eneo.",
    );
  return { tenantId: "", userId: "", ...origin };
}

export function equalSecret(left: string, right: string): boolean {
  return timingSafeEqual(
    createHash("sha256").update(left).digest(),
    createHash("sha256").update(right).digest(),
  );
}

/**
 * One stateless MCP endpoint per tool group at POST /mcp/{slug}. Only Eneo's backend calls it,
 * over a private network, with the shared bearer from TOOL_RUNTIME_TOKEN. Browsers never reach
 * this server, so any request carrying an Origin header is refused.
 */
export function createHandler(options: ServerOptions) {
  let active = 0;
  const endpoints = new Map(options.endpoints.map((e) => [e.slug, e]));

  return async function fetch(request: Request): Promise<Response> {
    const requestId = crypto.randomUUID();
    const url = new URL(request.url);
    if (url.pathname === "/health/live" || url.pathname === "/health/ready")
      return Response.json({ status: "ok", version: VERSION });
    const match = /^\/mcp\/([a-z][a-z0-9-]*)$/.exec(url.pathname);
    const endpoint = match ? endpoints.get(match[1]!) : undefined;
    if (!endpoint) return new Response("Not found", { status: 404 });
    if (request.headers.has("origin")) return new Response("Forbidden origin", { status: 403 });
    const header = request.headers.get("authorization") ?? "";
    if (!header.startsWith("Bearer ") || !equalSecret(header.slice(7), options.token))
      return new Response("Unauthorized", {
        status: 401,
        headers: { "www-authenticate": "Bearer" },
      });
    if (request.method !== "POST")
      return new Response("Method not allowed", { status: 405, headers: { allow: "POST" } });
    if (!request.headers.get("content-type")?.startsWith("application/json"))
      return new Response("Expected application/json", { status: 415 });
    if (active >= options.maxConcurrency)
      return new Response("Busy", { status: 429, headers: { "retry-after": "2" } });
    active++;
    try {
      const body = await boundedJson(request);
      const mcp = new McpServer({ name: `eneo-tool-runtime-${endpoint.slug}`, version: VERSION });
      for (const tool of endpoint.tools) {
        mcp.registerTool(
          tool.name,
          {
            title: tool.title,
            description: tool.description,
            inputSchema: tool.inputSchema,
            annotations: {
              readOnlyHint: tool.readOnly,
              destructiveHint: false,
              openWorldHint: false,
            },
          },
          async (input) => {
            try {
              const output = await deadline(
                tool.execute(input, callContext(request, endpoint)),
                endpoint.toolTimeoutMs,
              );
              const result = output instanceof RichResult ? output.structured : output;
              const files = output instanceof RichResult ? output.files : [];
              const images = output instanceof RichResult ? output.images : [];
              const text = JSON.stringify(result);
              if (Buffer.byteLength(text) > MAX_RESULT_BYTES)
                throw new ToolError("RESULT_TOO_LARGE", "Result exceeds the byte limit.");
              if (
                [...files.map((f) => f.blob), ...images.map((i) => i.data)].reduce(
                  (n, data) => n + (data.length * 3) / 4,
                  0,
                ) > MAX_FILE_BYTES
              )
                throw new ToolError("RESULT_TOO_LARGE", "Produced files exceed the byte limit.");
              return {
                content: [
                  { type: "text" as const, text },
                  ...images.map((image) => ({
                    type: "image" as const,
                    data: image.data,
                    mimeType: image.mimeType,
                  })),
                  ...files.map((file) => ({
                    type: "resource" as const,
                    resource: { uri: file.uri, mimeType: file.mimeType, blob: file.blob },
                  })),
                ],
                structuredContent: result,
              };
            } catch (error) {
              const safe = publicError(error);
              if (safe.code === "INTERNAL_ERROR")
                console.error(
                  JSON.stringify({ request_id: requestId, tool: tool.name, error: String(error) }),
                );
              return {
                isError: true,
                content: [
                  {
                    type: "text" as const,
                    text: `${safe.code}: ${safe.message} Request ID: ${requestId}`,
                  },
                ],
              };
            }
          },
        );
      }
      const transport = new WebStandardStreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true,
      });
      await mcp.connect(transport);
      const response = await transport.handleRequest(request, { parsedBody: body });
      response.headers.set("x-request-id", requestId);
      response.headers.set("cache-control", "no-store");
      return response;
    } catch (error) {
      return Response.json(
        {
          error: error instanceof BodyError ? error.message : "Invalid MCP request",
          request_id: requestId,
        },
        { status: error instanceof BodyError ? error.status : 400 },
      );
    } finally {
      active--;
    }
  };
}

class BodyError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function deadline<T>(operation: Promise<T>, milliseconds: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  try {
    return await Promise.race([
      operation,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new ToolError("TIMEOUT", "Operation exceeded its deadline.")),
          milliseconds,
        );
      }),
    ]);
  } finally {
    clearTimeout(timer!);
  }
}

async function boundedJson(request: Request): Promise<unknown> {
  if (!request.body) throw new BodyError("Missing body", 400);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    void reader.cancel();
  }, BODY_TIMEOUT_MS);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (timedOut) throw new BodyError("Request body timed out", 408);
      if (done) break;
      bytes += value.length;
      if (bytes > MAX_BODY_BYTES) {
        await reader.cancel();
        throw new BodyError("Request too large", 413);
      }
      chunks.push(value);
    }
  } finally {
    clearTimeout(timer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString());
  } catch {
    throw new BodyError("Invalid JSON", 400);
  }
}
