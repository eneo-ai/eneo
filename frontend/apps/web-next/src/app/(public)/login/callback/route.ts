import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { buildLoginDiagnosticsUrl } from "@/lib/auth/login-diagnostics";
import { sessionFromEneoJwt } from "@/lib/auth/password";
import { sealedSessionCookie } from "@/lib/auth/session";
import { safeNextPath } from "@/lib/auth/safe-next";
import { FEDERATION_TXN_COOKIE, openFederationTxn } from "@/lib/auth/session-codec";
import { env } from "@/lib/env";

function failedRedirect(detailCode: string) {
  const response = NextResponse.redirect(
    buildLoginDiagnosticsUrl("/login", env.APP_ORIGIN, {
      message: "oidc_callback_failed",
      detailCode
    })
  );
  response.cookies.delete(FEDERATION_TXN_COOKIE);
  return response;
}

/** Completes backend-first tenant federation and establishes the web-next session cookie. */
export async function GET(request: NextRequest) {
  const raw = request.cookies.get(FEDERATION_TXN_COOKIE)?.value;
  const txn = raw ? await openFederationTxn(raw, env.SESSION_SECRET) : null;
  const callbackState = request.nextUrl.searchParams.get("state");
  if (!txn || !callbackState || txn.state !== callbackState) {
    return failedRedirect("invalid_login_attempt");
  }
  const oauthError = request.nextUrl.searchParams.get("error");
  if (oauthError) {
    return failedRedirect("identity_provider_error");
  }

  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  if (!code || !state) {
    return failedRedirect(code ? "no_state_received" : "no_code_received");
  }

  let response: Response;
  try {
    response = await fetch(`${env.ENEO_BACKEND_URL}/api/v1/auth/callback`, {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json"
      },
      body: JSON.stringify({ code, state }),
      redirect: "error",
      signal: AbortSignal.timeout(15_000)
    });
  } catch {
    return failedRedirect("network_error");
  }

  if (!response.ok) {
    const traceId =
      response.headers.get("x-trace-id") ?? response.headers.get("x-correlation-id") ?? undefined;
    const failure = NextResponse.redirect(
      buildLoginDiagnosticsUrl("/login", env.APP_ORIGIN, {
        message: "oidc_callback_failed",
        detailCode:
          response.status === 403
            ? "access_denied"
            : response.status === 401
              ? "unauthorized"
              : `http_${response.status}`,
        correlation: traceId
      })
    );
    failure.cookies.delete(FEDERATION_TXN_COOKIE);
    return failure;
  }

  const body = z
    .object({ access_token: z.string() })
    .safeParse(await response.json().catch(() => null));
  const session = body.success ? sessionFromEneoJwt(body.data.access_token) : null;
  if (!session) {
    return failedRedirect("missing_access_token");
  }

  const redirect = NextResponse.redirect(new URL(safeNextPath(txn.next), env.APP_ORIGIN));
  const cookie = await sealedSessionCookie(session);
  redirect.cookies.set(cookie.name, cookie.value, cookie.options);
  redirect.cookies.delete(FEDERATION_TXN_COOKIE);
  return redirect;
}
