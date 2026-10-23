import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { env } from "@/lib/env";
import { safeNextPath } from "@/lib/auth/safe-next";
import {
  FEDERATION_TXN_COOKIE,
  FEDERATION_TXN_MAX_AGE,
  sealFederationTxn
} from "@/lib/auth/session-codec";

const authorizationSchema = z.object({
  authorization_url: z.url({ protocol: /^https?$/ }),
  state: z.string().min(1)
});

/** Starts federation only on a browser navigation, never during SSR. */
export async function GET(request: NextRequest) {
  const tenant = request.nextUrl.searchParams.get("tenant");
  if (tenant !== null && !/^[a-z0-9-]+$/.test(tenant)) {
    return NextResponse.json({ message: "Invalid tenant" }, { status: 400 });
  }
  const url = new URL("/api/v1/auth/initiate", env.ENEO_BACKEND_URL);
  if (tenant) url.searchParams.set("tenant", tenant);
  url.searchParams.set("redirect_uri", env.APP_ORIGIN + "/login/callback");

  try {
    const backend = await fetch(url, {
      headers: { accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
      redirect: "error"
    });
    if (!backend.ok) throw new Error("Federation unavailable");
    const authorization = authorizationSchema.parse(await backend.json());
    const response = NextResponse.redirect(authorization.authorization_url);
    response.headers.set("cache-control", "no-store");
    response.cookies.set(
      FEDERATION_TXN_COOKIE,
      await sealFederationTxn(
        {
          state: authorization.state,
          next: safeNextPath(request.nextUrl.searchParams.get("next"))
        },
        env.SESSION_SECRET
      ),
      {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge: FEDERATION_TXN_MAX_AGE
      }
    );
    return response;
  } catch {
    const response = NextResponse.redirect(
      new URL("/login?message=oidc_callback_failed", env.APP_ORIGIN)
    );
    response.cookies.delete(FEDERATION_TXN_COOKIE);
    return response;
  }
}
