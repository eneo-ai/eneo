import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/**
 * Uploaded icons are public on the backend (an icon id is not guessable and
 * shows nothing but the image). The embed page shows a persona's avatar
 * from here, under its own origin, since it cannot reach the backend; the
 * signed-in app keeps using the session-bound proxy for the same images.
 */
export async function GET(request: NextRequest, { params }: RouteContext<"/api/v1/icons/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ message: "Not found" }, { status: 404 });

  const headers = new Headers();
  for (const name of ["accept", "if-none-match", "if-modified-since"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const backendResponse = await fetch(
    `${env.ENEO_BACKEND_URL.replace(/\/$/, "")}/api/v1/icons/${id}/`,
    { headers, redirect: "manual", signal: request.signal }
  );

  const responseHeaders = new Headers();
  for (const name of ["content-type", "cache-control", "etag", "last-modified"]) {
    const value = backendResponse.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  responseHeaders.set("x-content-type-options", "nosniff");
  return new Response(backendResponse.body, {
    status: backendResponse.status,
    headers: responseHeaders
  });
}
