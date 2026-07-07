import { NextRequest, NextResponse } from "next/server";
import { buildLoginDiagnosticsUrl } from "@/lib/auth/login-diagnostics";
import { sessionFromEneoJwt } from "@/lib/auth/password";
import { sealedSessionCookie } from "@/lib/auth/session";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { env } from "@/lib/env";

function failedRedirect(detailCode: string, rawDetail?: string) {
  return NextResponse.redirect(
    buildLoginDiagnosticsUrl("/login", env.APP_ORIGIN, {
      message: "oidc_callback_failed",
      detailCode,
      rawDetail
    })
  );
}

/** Completes backend-first tenant federation and establishes the web-next session cookie. */
export async function GET(request: NextRequest) {
  const oauthError = request.nextUrl.searchParams.get("error");
  if (oauthError) {
    return failedRedirect(
      oauthError,
      request.nextUrl.searchParams.get("error_description") ?? undefined
    );
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
      body: JSON.stringify({ code, state })
    });
  } catch (error) {
    return failedRedirect("network_error", error instanceof Error ? error.message : undefined);
  }

  if (!response.ok) {
    const traceId =
      response.headers.get("x-trace-id") ?? response.headers.get("x-correlation-id") ?? undefined;
    const detail = await response.text().catch(() => undefined);
    return NextResponse.redirect(
      buildLoginDiagnosticsUrl("/login", env.APP_ORIGIN, {
        message: "oidc_callback_failed",
        detailCode:
          response.status === 403
            ? "access_denied"
            : response.status === 401
              ? "unauthorized"
              : `http_${response.status}`,
        correlation: traceId,
        rawDetail: detail || undefined
      })
    );
  }

  const body = (await response.json()) as { access_token?: string };
  const session = body.access_token ? sessionFromEneoJwt(body.access_token) : null;
  if (!session) {
    return failedRedirect("missing_access_token");
  }

  const redirect = NextResponse.redirect(new URL(DEFAULT_LANDING, env.APP_ORIGIN));
  const cookie = await sealedSessionCookie(session);
  redirect.cookies.set(cookie.name, cookie.value, cookie.options);
  return redirect;
}
