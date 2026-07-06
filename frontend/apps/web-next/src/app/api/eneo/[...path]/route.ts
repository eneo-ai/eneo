import { NextRequest, NextResponse } from "next/server";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { env } from "@/lib/env";

/**
 * Same-origin REST proxy for client components: /api/eneo/api/v1/* is
 * forwarded to ${ENEO_BACKEND_URL}/api/v1/*. The browser never holds a
 * backend token; this route swaps the session cookie for a bearer header.
 * Authorization stays the backend's job — the proxy only requires a session.
 *
 * Chat streaming does NOT go through here (Phase 5 has its own handler).
 */

/** Request headers forwarded to the backend (cookie et al. stay behind). */
const FORWARDED_REQUEST_HEADERS = ["accept", "accept-language", "content-type"];

/**
 * The only browser cookie forwarded to the backend. Audit-log access is gated
 * by a short-lived HTTP-only `audit_session_id` cookie the backend sets on
 * POST /audit/access-session; everything else (incl. the web-next session
 * cookie) deliberately stays behind so it never leaks to the backend.
 */
const AUDIT_SESSION_COOKIE = "audit_session_id";

/**
 * Re-scope a backend Set-Cookie for the proxy origin: the backend scopes the
 * audit cookie to `Path=/api/v1`, but the browser reaches it under
 * `/api/eneo/api/v1`, so rewrite the path and drop the backend Domain.
 */
function rescopeSetCookie(setCookie: string): string {
  return setCookie
    .replace(/;\s*Path=\/api\/v1\b/i, "; Path=/api/eneo/api/v1")
    .replace(/;\s*Domain=[^;]+/i, "");
}

/** Response headers forwarded back to the browser. Deliberately excludes
 * content-encoding/content-length: fetch already decompressed the body. */
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "x-trace-id",
  "x-correlation-id"
];

async function proxyRequest(request: NextRequest): Promise<Response> {
  const token = await getAccessTokenOrNull();
  if (!token) {
    return NextResponse.json({ message: "Not authenticated" }, { status: 401 });
  }

  // Read the path from pathname rather than the [...path] params so the
  // trailing slash survives (backend routes are slash-sensitive, and
  // skipTrailingSlashRedirect keeps Next from stripping it before we run).
  const path = request.nextUrl.pathname.replace(/^\/api\/eneo\//, "");
  if (!path.startsWith("api/v1/")) {
    return NextResponse.json({ message: "Unknown API path" }, { status: 404 });
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("authorization", `Bearer ${token}`);

  const auditSession = request.cookies.get(AUDIT_SESSION_COOKIE);
  if (auditSession) headers.set("cookie", `${AUDIT_SESSION_COOKIE}=${auditSession.value}`);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const backendResponse = await fetch(
    `${env.ENEO_BACKEND_URL.replace(/\/$/, "")}/${path}${request.nextUrl.search}`,
    {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      // Streaming a request body through Node's fetch requires half duplex.
      ...(hasBody ? { duplex: "half" } : {}),
      redirect: "manual"
    } as RequestInit
  );

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = backendResponse.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  // Authenticated responses must never land in shared or disk caches.
  responseHeaders.set("cache-control", "no-store");

  // Forward the audit access-session cookie back to the browser, re-scoped to
  // the proxy path so it rides along on subsequent /api/eneo audit calls.
  for (const setCookie of backendResponse.headers.getSetCookie()) {
    if (setCookie.startsWith(`${AUDIT_SESSION_COOKIE}=`)) {
      responseHeaders.append("set-cookie", rescopeSetCookie(setCookie));
    }
  }

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    headers: responseHeaders
  });
}

export {
  proxyRequest as GET,
  proxyRequest as POST,
  proxyRequest as PUT,
  proxyRequest as PATCH,
  proxyRequest as DELETE
};
