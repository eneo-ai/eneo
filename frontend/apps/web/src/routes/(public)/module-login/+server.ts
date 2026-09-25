import { EneoAccessTokenCookie, EneoIdTokenCookie } from "$lib/features/auth/auth.server";
import type { RequestHandler } from "./$types";

const RESPONSE_HEADERS = {
  "Cache-Control": "private, no-store, max-age=0",
  "Referrer-Policy": "no-referrer",
  "X-Robots-Tag": "noindex, nofollow, noarchive"
} as const;
// This public route performs its own session gate so every response, including
// the login redirect, receives the security headers above.
const REQUEST_PARAMETERS = new Set(["module_key", "redirect_uri", "state"]);

type FailureReason = "invalid_request" | "module_unavailable" | "service_unavailable";

function redirectResponse(location: string, status = 303): Response {
  return new Response(null, {
    status,
    headers: { ...RESPONSE_HEADERS, Location: location }
  });
}

function failureResponse(reason: FailureReason): Response {
  return redirectResponse(`/module-login/failed?reason=${reason}`);
}

function exactlyOneNonEmpty(searchParams: URLSearchParams, name: string): string | null {
  const values = searchParams.getAll(name);
  if (values.length !== 1 || values[0].trim().length === 0) {
    return null;
  }
  return values[0];
}

function validatedRedirectTarget(value: unknown): string | null {
  if (typeof value !== "string" || value.length === 0) {
    return null;
  }

  try {
    const target = new URL(value);
    if (
      (target.protocol !== "https:" && target.protocol !== "http:") ||
      target.username.length > 0 ||
      target.password.length > 0
    ) {
      return null;
    }
  } catch {
    return null;
  }

  // Validation must not normalize or reconstruct the backend-generated target.
  return value;
}

function loginResponse(url: URL, cookies: Parameters<RequestHandler>[0]["cookies"]): Response {
  cookies.delete(EneoIdTokenCookie, { path: "/" });
  cookies.delete(EneoAccessTokenCookie, { path: "/" });
  const resumePath = url.pathname + url.search;
  const loginQuery = new URLSearchParams({ next: resumePath });
  return redirectResponse(`/login?${loginQuery.toString()}`);
}

export const GET: RequestHandler = async ({ url, locals, fetch, cookies }) => {
  if (Array.from(url.searchParams.keys()).some((name) => !REQUEST_PARAMETERS.has(name))) {
    return failureResponse("invalid_request");
  }

  const moduleKey = exactlyOneNonEmpty(url.searchParams, "module_key");
  const redirectUri = exactlyOneNonEmpty(url.searchParams, "redirect_uri");
  const state = exactlyOneNonEmpty(url.searchParams, "state");

  if (moduleKey === null || redirectUri === null || state === null) {
    return failureResponse("invalid_request");
  }

  if (!locals.id_token) {
    return loginResponse(url, cookies);
  }

  const backendBaseUrl = locals.environment.baseUrl;
  if (!backendBaseUrl) {
    return failureResponse("service_unavailable");
  }

  let response: Response;
  try {
    response = await fetch(new URL("/api/v1/module-auth/tickets/", backendBaseUrl), {
      method: "POST",
      headers: {
        Authorization: `Bearer ${locals.id_token}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        module_key: moduleKey,
        redirect_uri: redirectUri,
        state
      })
    });
  } catch {
    return failureResponse("service_unavailable");
  }

  if (response.status === 401) {
    return loginResponse(url, cookies);
  }
  if (response.status === 422) {
    return failureResponse("invalid_request");
  }
  if ([400, 403, 404].includes(response.status)) {
    return failureResponse("module_unavailable");
  }
  if (!response.ok) {
    return failureResponse("service_unavailable");
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return failureResponse("service_unavailable");
  }
  const redirectTarget = validatedRedirectTarget(
    typeof body === "object" && body !== null && "redirect_target" in body
      ? body.redirect_target
      : null
  );

  return redirectTarget === null
    ? failureResponse("service_unavailable")
    : redirectResponse(redirectTarget);
};

export const HEAD: RequestHandler = () =>
  new Response(null, {
    status: 405,
    headers: { ...RESPONSE_HEADERS, Allow: "GET" }
  });
