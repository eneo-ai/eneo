import { timingSafeEqual, createHash } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { publicError, ToolError } from "./errors";
import { Scheduler } from "./scheduler";
import { callerGroup, checkCancellation, event, work } from "./work";
import { probeUrl } from "./tools/tabular/download";
import { RichResult, type CallContext, type ToolDefinition } from "./tools/types";

const VERSION = process.env.APP_VERSION ?? "0.0.0-dev";
const MAX_BODY_BYTES = 256 * 1024;
const MAX_RESULT_BYTES = 512 * 1024;
// Files a tool returns; matches Eneo's default MCP_TOOL_FILE_MAX_BYTES for one result.
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const BODY_TIMEOUT_MS = 10_000;
// The media type of a tool's view (MCP Apps).
const VIEW_MIME_TYPE = "text/html;profile=mcp-app";

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
  maxQueue?: number;
  maxQueuePerGroup?: number;
  confinement?: { files: boolean; tcp: boolean };
  nativeStatus?: () => { active: number; queued: number };
  allowedFileOrigins?: string[];
  revision?: string;
  version?: string;
  /** Eneo's built-in document template, served at GET /templates/builtin.docx?language=sv|en. */
  builtinTemplate?: (language: "sv" | "en") => Promise<Buffer>;
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
  const origin = {
    ...(fileOrigin ? { fileOrigin } : {}),
    ...(request.headers.get("x-eneo-tool-views") === "shown" ? { showsViews: true } : {}),
  };
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
  let controlActive = 0;
  const scheduler = new Scheduler(
    options.maxConcurrency,
    options.maxQueue ?? 32,
    options.maxQueuePerGroup ?? 8,
  );
  const version = options.version ?? VERSION;
  const revision = options.revision ?? process.env.APP_REVISION ?? "unknown";
  const endpoints = new Map(options.endpoints.map((e) => [e.slug, e]));

  return async function fetch(request: Request): Promise<Response> {
    const requestId = crypto.randomUUID();
    const url = new URL(request.url);
    if (url.pathname === "/health/live" || url.pathname === "/health/ready")
      return Response.json({ status: "ok" });
    const match = /^\/mcp\/([a-z][a-z0-9-]*)$/.exec(url.pathname);
    const endpoint = match ? endpoints.get(match[1]!) : undefined;
    const diagnostics = url.pathname === "/diagnostics";
    const template = url.pathname === "/templates/builtin.docx" && !!options.builtinTemplate;
    if (!endpoint && !diagnostics && !template) return new Response("Not found", { status: 404 });
    if (request.headers.has("origin")) return new Response("Forbidden origin", { status: 403 });
    const header = request.headers.get("authorization") ?? "";
    if (!header.startsWith("Bearer ") || !equalSecret(header.slice(7), options.token))
      return new Response("Unauthorized", {
        status: 401,
        headers: { "www-authenticate": "Bearer" },
      });
    if (template) {
      if (request.method !== "GET") return new Response("Method not allowed", { status: 405 });
      const language = url.searchParams.get("language") ?? "sv";
      if (language !== "sv" && language !== "en")
        return new Response("Unknown language", { status: 400 });
      if (controlActive >= 4) return new Response("Busy", { status: 429 });
      controlActive++;
      try {
        const bytes = await options.builtinTemplate!(language);
        return new Response(new Uint8Array(bytes), {
          headers: {
            "content-type":
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "content-disposition": `attachment; filename="eneo-template-${language}.docx"`,
            "cache-control": "no-store",
          },
        });
      } catch (error) {
        return Response.json(publicError(error), { status: 500 });
      } finally {
        controlActive--;
      }
    }
    if (diagnostics) {
      if (request.method !== "GET") return new Response("Method not allowed", { status: 405 });
      if (controlActive >= 4) return new Response("Busy", { status: 429 });
      controlActive++;
      try {
        const origin = parseOrigin(request.headers.get("x-eneo-file-origin"));
        let fileOrigin = origin ? "unreachable" : "unknown";
        if (origin) {
          if (options.allowedFileOrigins?.length && !options.allowedFileOrigins.includes(origin))
            fileOrigin = "not_allowed";
          else {
            try {
              await probeUrl(origin, {
                allowed_origins: [{ origin, allow_private: true }],
                max_upload_bytes: 1,
                download_timeout_ms: 2500,
              });
              fileOrigin = "reachable";
            } catch {
              /* A TCP probe never proves file authorization. */
            }
          }
        }
        return Response.json(
          {
            version,
            revision,
            confinement: options.confinement ?? { files: false, tcp: false },
            endpoints: [...endpoints.keys()],
            execution: scheduler.status,
            native: options.nativeStatus?.() ?? { active: 0, queued: 0 },
            file_origin: fileOrigin,
          },
          { headers: { "cache-control": "no-store" } },
        );
      } finally {
        controlActive--;
      }
    }
    if (!endpoint) return new Response("Not found", { status: 404 });
    if (request.method !== "POST")
      return new Response("Method not allowed", { status: 405, headers: { allow: "POST" } });
    if (!request.headers.get("content-type")?.startsWith("application/json"))
      return new Response("Expected application/json", { status: 415 });
    if (active >= options.maxConcurrency + (options.maxQueue ?? 32) + 4)
      return new Response("Busy", { status: 429, headers: { "retry-after": "2" } });
    active++;
    let control = false;
    try {
      const body = await boundedJson(request);
      if (
        !body ||
        typeof body !== "object" ||
        (body as { method?: string }).method !== "tools/call"
      ) {
        if (controlActive >= 4) return new Response("Busy", { status: 429 });
        controlActive++;
        control = true;
      }
      const mcp = new McpServer({ name: `eneo-tool-runtime-${endpoint.slug}`, version });
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
            ...(tool.view ? { _meta: { ui: { resourceUri: tool.view.uri } } } : {}),
          },
          async (input) => {
            try {
              const ctx = callContext(request, endpoint);
              const controller = new AbortController();
              const cancel = () =>
                controller.abort(new ToolError("CANCELLED", "The operation was cancelled."));
              request.signal.addEventListener("abort", cancel, { once: true });
              if (request.signal.aborted) cancel();
              const timer = setTimeout(
                () =>
                  controller.abort(new ToolError("TIMEOUT", "Operation exceeded its deadline.")),
                endpoint.toolTimeoutMs,
              );
              const state = {
                group: callerGroup(ctx.tenantId),
                requestId,
                signal: controller.signal,
                cleanup: [] as Array<() => void | Promise<void>>,
              };
              const started = performance.now();
              let began: number | undefined;
              const output = await work.run(state, async () => {
                try {
                  const result = await scheduler.run(async () => {
                    began = performance.now();
                    checkCancellation();
                    const result = await tool.execute(input, ctx);
                    checkCancellation();
                    return result;
                  });
                  event("tool_completed", {
                    tool: tool.name,
                    queue_ms: Math.round((began ?? performance.now()) - started),
                    duration_ms: Math.round(performance.now() - (began ?? started)),
                  });
                  return result;
                } catch (error) {
                  event("tool_failed", {
                    tool: tool.name,
                    code: publicError(error).code,
                    queue_ms: Math.round((began ?? performance.now()) - started),
                    duration_ms: began === undefined ? 0 : Math.round(performance.now() - began),
                    cancelled: controller.signal.aborted,
                  });
                  throw error;
                } finally {
                  clearTimeout(timer);
                  request.signal.removeEventListener("abort", cancel);
                  const releases = await Promise.allSettled(
                    state.cleanup.reverse().map((release) => Promise.resolve().then(release)),
                  );
                  const failed = releases.filter((result) => result.status === "rejected").length;
                  if (failed) event("cleanup_failed", { count: failed });
                }
              });
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
                  JSON.stringify({ request_id: requestId, tool: tool.name, error: safe.code }),
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
      // A tool's view is read by the host as a resource and shown beside the tool's call.
      const views = new Map(
        endpoint.tools.flatMap((tool) => (tool.view ? [[tool.view.uri, tool.view] as const] : [])),
      );
      for (const view of views.values())
        mcp.registerResource(
          view.uri.slice(view.uri.lastIndexOf("/") + 1),
          view.uri,
          { mimeType: VIEW_MIME_TYPE },
          () => ({
            contents: [
              {
                uri: view.uri,
                mimeType: VIEW_MIME_TYPE,
                text: view.html,
                ...(view.ui ? { _meta: { ui: view.ui } } : {}),
              },
            ],
          }),
        );
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
      if (control) controlActive--;
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
