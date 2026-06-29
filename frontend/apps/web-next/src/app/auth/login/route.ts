import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import { isOidcEnabled, startAuthorization } from "@/lib/auth/oidc";
import { sealTxn } from "@/lib/auth/session-codec";
import { TXN_COOKIE } from "@/lib/auth/session";

const TXN_MAX_AGE_SECONDS = 60 * 10;

/** Starts the OIDC authorization code flow (PKCE + state + nonce). */
export async function GET(request: NextRequest) {
  if (!isOidcEnabled()) {
    return NextResponse.redirect(new URL("/login", env.APP_ORIGIN));
  }

  const next = request.nextUrl.searchParams.get("next") ?? undefined;
  const prompt = request.nextUrl.searchParams.get("prompt") ?? undefined;

  let authorization;
  try {
    authorization = await startAuthorization(undefined, { prompt });
  } catch {
    return NextResponse.redirect(new URL("/login/failed", env.APP_ORIGIN));
  }

  const txn = await sealTxn(
    {
      verifier: authorization.verifier,
      state: authorization.state,
      nonce: authorization.nonce,
      next
    },
    env.SESSION_SECRET,
    TXN_MAX_AGE_SECONDS
  );

  const response = NextResponse.redirect(authorization.url);
  response.cookies.set(TXN_COOKIE, txn, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: TXN_MAX_AGE_SECONDS
  });
  return response;
}
