import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";

const TENANT_SLUG_PATTERN = /^[a-z0-9-]+$/;

export async function GET(request: NextRequest) {
  const tenant = request.nextUrl.searchParams.get("tenant");
  if (!tenant || !TENANT_SLUG_PATTERN.test(tenant)) {
    return NextResponse.json({ message: "Invalid tenant" }, { status: 400 });
  }

  const url = new URL("/api/v1/auth/initiate", env.ENEO_BACKEND_URL);
  url.searchParams.set("tenant", tenant);

  const response = await fetch(url, {
    headers: { accept: "application/json" },
    cache: "no-store"
  });

  if (!response.ok) {
    return NextResponse.json(
      { message: "Failed to initiate authentication" },
      { status: response.status }
    );
  }

  return NextResponse.json(await response.json(), {
    headers: { "cache-control": "no-store" }
  });
}
