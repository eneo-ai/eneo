import { dev } from "$app/environment";
import { DASHBOARD_URL } from "$lib/core/constants";
import { detectMobile } from "$lib/core/detectMobile";
import { getFeatureFlags } from "$lib/core/flags.server";
import { authenticateUser, clearFrontendCookies } from "$lib/features/auth/auth.server";
import { IntricError, type IntricErrorCode } from "@intric/intric-js";
import { redirect, type Handle, type HandleFetch, type HandleServerError } from "@sveltejs/kit";
import { env } from "$env/dynamic/private";
import { getEnvironmentConfig } from "./lib/core/environment.server";
import { sequence } from "@sveltejs/kit/hooks";
import { paraglideMiddleware } from "$lib/paraglide/server";
import { logger } from "$lib/utils/logger";

function routeRequiresLogin(route: { id: string | null }): boolean {
  const routeIsPublic = route.id?.includes("(public)") ?? false;
  return !routeIsPublic;
}

const authHandle: Handle = async ({ event, resolve }) => {
  // Clear authentication cookies if the 'clear_cookies' URL parameter is present
  if (event.url.searchParams.get("clear_cookies")) {
    clearFrontendCookies(event);
  }

  const tokens = authenticateUser(event);
  const isLoggedIn = tokens.id_token != undefined;

  // DEBUG LOGGING
  logger.log(`[AUTH] Path: ${event.url.pathname}`);
  logger.log(`[AUTH] Has id_token: ${isLoggedIn}`);
  logger.log(`[AUTH] Token preview: ${tokens.id_token ? tokens.id_token.substring(0, 20) + '...' : 'NONE'}`);
  logger.log(`[AUTH] All cookies: ${event.cookies.getAll().map(c => c.name).join(', ')}`);
  logger.log(`[AUTH] Route requires login: ${routeRequiresLogin(event.route)}`);

  if (routeRequiresLogin(event.route)) {
    if (!isLoggedIn) {
      logger.log(`[AUTH] ❌ NO TOKEN - Redirecting to login`);
      const redirectUrl = encodeURIComponent(event.url.pathname + event.url.search);
      redirect(302, `/login?next=${redirectUrl}`);
    }
    logger.log(`[AUTH] ✅ Token valid - allowing access`);

    const isDashboard = event.url.pathname.startsWith("/dashboard");

    if (!isDashboard) {
      const userAgent = event.request.headers.get("user-agent");
      const isMobileOrTablet = userAgent ? detectMobile(userAgent) : false;
      if (isMobileOrTablet) {
        redirect(302, DASHBOARD_URL);
      }
    }
  }

  event.locals.id_token = tokens.id_token ?? null;
  event.locals.access_token = tokens.access_token ?? null;
  event.locals.featureFlags = getFeatureFlags();
  event.locals.environment = getEnvironmentConfig();

  return resolve(event);
};

const paraglideHandle: Handle = ({ event, resolve }) =>
  paraglideMiddleware(event.request, ({ request: localizedRequest, locale }) => {
    event.request = localizedRequest;
    return resolve(event, {
      transformPageChunk: ({ html }) => {
        return html.replace("%lang%", locale);
      }
    });
  });

export const handle = sequence(paraglideHandle, authHandle);

export const handleError: HandleServerError = async ({ error, status, message }) => {
  let code: IntricErrorCode = 0;
  if (error instanceof IntricError) {
    status = error.status;
    message = error.getReadableMessage();
    code = error.code;
  }

  if (dev) {
    console.error("server error", error);
  }

  return {
    status,
    message,
    code
  };
};

export const handleFetch: HandleFetch = async ({ request, fetch }) => {
  const originalUrl = request.url;
  const hasAuthHeader = request.headers.has('Authorization') || request.headers.has('authorization');
  const authPreview = request.headers.get('Authorization') || request.headers.get('authorization');

  // Log all headers from original request
  const originalHeaders: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    originalHeaders[key] = key.toLowerCase() === 'authorization' ? value.substring(0, 20) + '...' : value;
  });

  logger.log(`[HANDLE_FETCH] Method: ${request.method}, URL: ${originalUrl}`);
  logger.log(`[HANDLE_FETCH] Has Authorization header: ${hasAuthHeader}`);
  logger.log(`[HANDLE_FETCH] Auth header preview: ${authPreview ? authPreview.substring(0, 20) + '...' : 'NONE'}`);
  logger.log(`[HANDLE_FETCH] All original headers: ${JSON.stringify(originalHeaders)}`);
  logger.log(`[HANDLE_FETCH] INTRIC_BACKEND_URL: ${env.INTRIC_BACKEND_URL}`);
  logger.log(`[HANDLE_FETCH] INTRIC_BACKEND_SERVER_URL: ${env.INTRIC_BACKEND_SERVER_URL}`);

  const hasServerUrl = !!env.INTRIC_BACKEND_SERVER_URL;
  const hasBackendUrl = !!env.INTRIC_BACKEND_URL;
  const startsWithBackend = env.INTRIC_BACKEND_URL && request.url.startsWith(env.INTRIC_BACKEND_URL);

  logger.log(`[HANDLE_FETCH] Has SERVER_URL: ${hasServerUrl}, Has BACKEND_URL: ${hasBackendUrl}, Starts with backend: ${startsWithBackend}`);

  if (
    env.INTRIC_BACKEND_SERVER_URL &&
    env.INTRIC_BACKEND_URL &&
    request.url.startsWith(env.INTRIC_BACKEND_URL)
  ) {
    const newUrl = request.url.replace(env.INTRIC_BACKEND_URL, env.INTRIC_BACKEND_SERVER_URL);
    logger.log(`[HANDLE_FETCH] ✅ Rewriting: ${originalUrl} → ${newUrl}`);

    // Explicitly copy all request properties to new URL
    // Create a NEW Headers object to ensure headers are properly copied
    const newHeaders = new Headers(request.headers);

    const init: RequestInit = {
      method: request.method,
      headers: newHeaders,
      body: request.method !== 'GET' && request.method !== 'HEAD' ? request.body : undefined,
      mode: request.mode,
      credentials: request.credentials,
      cache: request.cache,
      redirect: request.redirect,
      referrer: request.referrer,
      integrity: request.integrity,
      signal: request.signal
    };

    request = new Request(newUrl, init);

    // Verify headers are preserved after rewriting
    const hasAuthAfter = request.headers.has('Authorization') || request.headers.has('authorization');

    // Log all headers after rewrite
    const rewrittenHeaders: Record<string, string> = {};
    request.headers.forEach((value, key) => {
      rewrittenHeaders[key] = key.toLowerCase() === 'authorization' ? value.substring(0, 20) + '...' : value;
    });

    logger.log(`[HANDLE_FETCH] Headers preserved after rewrite: ${hasAuthAfter}`);
    logger.log(`[HANDLE_FETCH] All rewritten headers: ${JSON.stringify(rewrittenHeaders)}`);
  } else {
    logger.log(`[HANDLE_FETCH] ❌ NOT rewriting`);
  }

  try {
    const response = await fetch(request);
    logger.log(`[HANDLE_FETCH] Response status: ${response.status} for ${originalUrl}`);

    if (!response.ok) {
      logger.error(`[HANDLE_FETCH] ❌ Request failed: ${response.status} ${response.statusText} for ${originalUrl}`);

      // For 401 errors, try to log the response body to see backend error message
      if (response.status === 401) {
        try {
          const clonedResponse = response.clone();
          const errorText = await clonedResponse.text();
          logger.error(`[HANDLE_FETCH] 401 Response body: ${errorText}`);
        } catch (e) {
          logger.error(`[HANDLE_FETCH] Could not read 401 response body`);
        }
      }
    }

    return response;
  } catch (error) {
    logger.error(`[HANDLE_FETCH] ❌ Fetch error for ${originalUrl}:`, error);
    throw error;
  }
};
