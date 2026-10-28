import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";

/**
 * The visitor surface of a widget, `/api/v1/widgets/wgt_…/*`, forwarded to the
 * backend at the same path. The embed page runs on this origin and, like the
 * rest of this app, never reaches the backend directly (the embed CSP allows
 * `connect-src 'self'` only). Nothing here is signed in: a visitor
 * authenticates with the token the backend minted for it, sent as its own
 * bearer header, and the backend's rate limits key on the visitor and on the
 * client address this app passes on. Only the endpoints a visitor uses are
 * forwarded, each with its one method.
 */

const PUBLIC_ID = /^wgt_[0-9A-Za-z]{22}$/;
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";

const ENDPOINTS: ReadonlyArray<{ path: RegExp; method: "GET" | "POST" }> = [
  { path: /^config\/$/, method: "GET" },
  { path: /^challenge\/$/, method: "GET" },
  { path: /^visitor-sessions\/$/, method: "POST" },
  { path: /^ask\/$/, method: "POST" },
  { path: new RegExp(`^sessions/${UUID}/$`), method: "GET" },
  { path: new RegExp(`^sessions/${UUID}/feedback/$`), method: "POST" }
];

/** Request headers forwarded to the backend (cookies never are). */
const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "authorization",
  "if-none-match"
];

/**
 * Response headers forwarded back. Content length and encoding stay behind:
 * fetch already decompressed the body. Retry-After tells the visitor how
 * long a rate limit lasts; the ETag lets the config request answer 304.
 */
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "etag",
  "retry-after",
  "x-trace-id",
  "x-correlation-id"
];

export function visitorEndpoint(
  pathname: string
): { publicId: string; path: string; method: "GET" | "POST" } | null {
  const match = /^\/api\/v1\/widgets\/([^/]+)\/(.*)$/.exec(pathname);
  if (!match) return null;
  const [, publicId, path] = match as unknown as [string, string, string];
  if (!PUBLIC_ID.test(publicId)) return null;
  const endpoint = ENDPOINTS.find((candidate) => candidate.path.test(path));
  return endpoint ? { publicId, path, method: endpoint.method } : null;
}

async function proxyVisitorRequest(request: NextRequest): Promise<Response> {
  // From the pathname, not the route params, so the trailing slash survives
  // (backend routes are slash-sensitive).
  const endpoint = visitorEndpoint(request.nextUrl.pathname);
  if (!endpoint) return NextResponse.json({ message: "Not found" }, { status: 404 });
  if (request.method !== endpoint.method) {
    return NextResponse.json(
      { message: "Method not allowed" },
      { status: 405, headers: { allow: endpoint.method } }
    );
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // The backend's per-address limits need the visitor's address, not this
  // app's. A reverse proxy in front of this app records it in
  // X-Forwarded-For; pass that chain on unchanged, for the backend's
  // trusted-proxy count to read, and add nothing when there is none.
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);

  const hasBody = endpoint.method === "POST";
  const backendResponse = await fetch(
    `${env.ENEO_BACKEND_URL.replace(/\/$/, "")}${request.nextUrl.pathname}${request.nextUrl.search}`,
    {
      method: endpoint.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Streaming a request body through Node's fetch requires half duplex.
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual",
      // A visitor who closes the panel mid-answer stops the backend's work too.
      signal: request.signal
    } as RequestInit
  );

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = backendResponse.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  // Tokens, conversations and configuration must never land in a cache.
  responseHeaders.set("cache-control", "no-store");
  responseHeaders.set("x-content-type-options", "nosniff");

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    headers: responseHeaders
  });
}

export { proxyVisitorRequest as GET, proxyVisitorRequest as POST };
