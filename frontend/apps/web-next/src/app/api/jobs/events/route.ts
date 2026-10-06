import { NextRequest, NextResponse } from "next/server";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { env } from "@/lib/env";

/**
 * Job events proxy: opens the backend's server-sent-events stream of the
 * signed-in user's job updates and passes it through untouched, the same way
 * the chat proxy streams answers. The browser never holds a backend token;
 * closing the EventSource aborts the upstream fetch.
 */
export async function GET(request: NextRequest): Promise<Response> {
  const token = await getAccessTokenOrNull();
  if (!token) {
    return NextResponse.json({ message: "Not authenticated" }, { status: 401 });
  }
  const backendResponse = await fetch(
    `${env.ENEO_BACKEND_URL.replace(/\/$/, "")}/api/v1/jobs/events/`,
    {
      headers: { authorization: `Bearer ${token}`, accept: "text/event-stream" },
      signal: request.signal
    }
  );
  const headers = new Headers();
  const contentType = backendResponse.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("cache-control", "no-store");
  // Reverse proxies must not buffer a stream that stays open for hours.
  headers.set("x-accel-buffering", "no");
  return new Response(backendResponse.body, { status: backendResponse.status, headers });
}

export const dynamic = "force-dynamic";
