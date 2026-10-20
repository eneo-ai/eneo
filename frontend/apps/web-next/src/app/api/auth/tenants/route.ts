import { NextResponse } from "next/server";
import { env } from "@/lib/env";

export async function GET() {
  const response = await fetch(`${env.ENEO_BACKEND_URL}/api/v1/auth/tenants`, {
    headers: { accept: "application/json" },
    cache: "no-store"
  });

  if (!response.ok) {
    return NextResponse.json({ tenants: [] }, { status: response.status });
  }

  return NextResponse.json(await response.json(), {
    headers: { "cache-control": "no-store" }
  });
}
