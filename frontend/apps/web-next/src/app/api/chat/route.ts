import { NextRequest, NextResponse } from "next/server";
import { getAccessTokenOrNull } from "@/lib/auth/session";
import { env } from "@/lib/env";

/**
 * Chat streaming proxy: forwards the conversation request to the backend's
 * version=3 endpoint (AI SDK UI Message Stream) and passes the SSE stream
 * through untouched. The browser never holds a backend token. Aborts
 * propagate to the upstream fetch; the backend persists partial answers.
 */
export async function POST(request: NextRequest): Promise<Response> {
  const token = await getAccessTokenOrNull();
  if (!token) {
    return NextResponse.json({ message: "Not authenticated" }, { status: 401 });
  }

  const backendResponse = await fetch(
    `${env.ENEO_BACKEND_URL.replace(/\/$/, "")}/api/v1/conversations/?version=3`,
    {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
        accept: "text/event-stream"
      },
      body: request.body,
      // Streaming a request body through Node's fetch requires half duplex.
      duplex: "half",
      signal: request.signal
    } as RequestInit
  );

  const headers = new Headers();
  for (const name of ["content-type", "x-vercel-ai-ui-message-stream", "x-trace-id"]) {
    const value = backendResponse.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("cache-control", "no-cache");

  return new Response(backendResponse.body, {
    status: backendResponse.status,
    headers
  });
}
