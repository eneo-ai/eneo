import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import {
  buildLoginDiagnosticsUrl,
  diagnosticsFromUnknownError
} from "@/lib/auth/login-diagnostics";
import { completeAuthorization } from "@/lib/auth/oidc";
import { safeNextPath } from "@/lib/auth/safe-next";
import { openTxn, type SessionPayload } from "@/lib/auth/session-codec";
import { sealedSessionCookie, TXN_COOKIE } from "@/lib/auth/session";

/** Completes the OIDC code exchange and establishes the session cookie. */
export async function GET(request: NextRequest) {
  const correlation = crypto.randomUUID();

  function failedRedirect(
    pathname: "/login" | "/login/failed",
    diagnostics: Parameters<typeof buildLoginDiagnosticsUrl>[2]
  ) {
    const response = NextResponse.redirect(
      buildLoginDiagnosticsUrl(pathname, env.APP_ORIGIN, {
        correlation,
        ...diagnostics
      })
    );
    response.cookies.delete(TXN_COOKIE);
    return response;
  }

  // The user canceled or the IdP rejected the request.
  const oauthError = request.nextUrl.searchParams.get("error");
  if (oauthError) {
    return failedRedirect("/login", {
      message: "oidc_callback_failed",
      detailCode: oauthError,
      rawDetail: request.nextUrl.searchParams.get("error_description") ?? undefined
    });
  }

  const rawTxn = request.cookies.get(TXN_COOKIE)?.value;
  const txn = rawTxn ? await openTxn(rawTxn, env.SESSION_SECRET) : null;
  if (!txn) {
    return failedRedirect("/login/failed", {
      message: "oidc_callback_failed",
      info: "missing_transaction",
      detailCode: "no_state_received"
    });
  }

  let tokens;
  try {
    tokens = await completeAuthorization(request.nextUrl, txn);
  } catch (error) {
    return failedRedirect(
      "/login",
      diagnosticsFromUnknownError(error, {
        message: "oidc_callback_failed",
        info: "token_exchange_failed"
      })
    );
  }

  if (!tokens.claims.email) {
    return failedRedirect("/login/failed", {
      message: "oidc_callback_failed",
      info: "missing_email_claim"
    });
  }

  const session: SessionPayload = {
    mode: "oidc",
    accessToken: tokens.accessToken,
    accessTokenExpiresAt: tokens.accessTokenExpiresAt,
    refreshToken: tokens.refreshToken,
    idToken: tokens.idToken,
    user: { email: tokens.claims.email, name: tokens.claims.name }
  };

  const target = safeNextPath(txn.next);
  const response = NextResponse.redirect(new URL(target, env.APP_ORIGIN));
  const cookie = await sealedSessionCookie(session);
  response.cookies.set(cookie.name, cookie.value, cookie.options);
  response.cookies.delete(TXN_COOKIE);
  return response;
}
