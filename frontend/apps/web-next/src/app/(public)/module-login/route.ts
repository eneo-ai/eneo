import { NextRequest, NextResponse } from "next/server";
import { env } from "@/lib/env";
import {
  loginPathToResume,
  MODULE_LOGIN_RESPONSE_HEADERS,
  moduleLoginFailurePath,
  moduleLoginResumePath,
  parseModuleLoginRequest,
  redirectTargetFromBody,
  ticketOutcome,
  type ModuleLoginFailureReason
} from "@/lib/auth/module-login";
import { getAccessTokenOrNull, SESSION_COOKIE } from "@/lib/auth/session";

/**
 * SSO hand-off for modules (see `@/lib/auth/module-login`). The route is
 * public in `proxy.ts` and gates the session itself, so every response, the
 * login redirect included, carries the no-store / no-referrer / noindex
 * headers. The ticket travels only in the module's `redirect_target`; it is
 * never logged or echoed.
 */

/** A plain Response: `NextResponse.redirect` would normalise the Location. */
function redirectResponse(location: string): Response {
  return new Response(null, {
    status: 303,
    headers: { ...MODULE_LOGIN_RESPONSE_HEADERS, Location: location }
  });
}

function failureResponse(reason: ModuleLoginFailureReason): Response {
  return redirectResponse(new URL(moduleLoginFailurePath(reason), env.APP_ORIGIN).href);
}

/** No usable session: drop the cookie (a dead one would bounce /login back
 * into the app) and resume the hand-off after login. */
function loginResponse(url: URL): Response {
  const response = NextResponse.redirect(
    new URL(loginPathToResume(moduleLoginResumePath(url)), env.APP_ORIGIN),
    { status: 303, headers: MODULE_LOGIN_RESPONSE_HEADERS }
  );
  response.cookies.delete(SESSION_COOKIE);
  return response;
}

export async function GET(request: NextRequest) {
  const url = request.nextUrl;
  const parameters = parseModuleLoginRequest(url.searchParams);
  if (!parameters) return failureResponse("invalid_request");

  const accessToken = await getAccessTokenOrNull();
  if (!accessToken) return loginResponse(url);

  let response: Response;
  try {
    response = await fetch(
      `${env.ENEO_BACKEND_URL.replace(/\/$/, "")}/api/v1/module-auth/tickets/`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${accessToken}`,
          accept: "application/json",
          "content-type": "application/json"
        },
        body: JSON.stringify({
          module_key: parameters.moduleKey,
          redirect_uri: parameters.redirectUri,
          state: parameters.state
        }),
        cache: "no-store"
      }
    );
  } catch {
    return failureResponse("service_unavailable");
  }

  const outcome = ticketOutcome(response.status);
  if (outcome.kind === "login") return loginResponse(url);
  if (outcome.kind === "failure") return failureResponse(outcome.reason);

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return failureResponse("service_unavailable");
  }
  const redirectTarget = redirectTargetFromBody(body);
  return redirectTarget === null
    ? failureResponse("service_unavailable")
    : redirectResponse(redirectTarget);
}

/** A HEAD must not issue a ticket. */
export function HEAD() {
  return new Response(null, {
    status: 405,
    headers: { ...MODULE_LOGIN_RESPONSE_HEADERS, Allow: "GET" }
  });
}
