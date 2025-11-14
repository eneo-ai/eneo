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

  if (routeRequiresLogin(event.route)) {
    if (!isLoggedIn) {
      const redirectUrl = encodeURIComponent(event.url.pathname + event.url.search);
      redirect(302, `/login?next=${redirectUrl}`);
    }

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

const headerFilterHandle: Handle = async ({ event, resolve }) => {
  const response = await resolve(event);

  // Filter oversized Link header to prevent HAProxy 502 Bad Gateway
  // HAProxy buffer limit: 16KB-64KB (effective header space = bufsize - maxrewrite)
  const linkHeader = response.headers.get('link');
  if (linkHeader && linkHeader.length > 12000) {
    console.warn(
      `[Headers] Link header too large (${linkHeader.length} bytes) - removing to prevent HAProxy 502. ` +
      `Consider disabling modulePreload in vite.config.ts.`
    );
    response.headers.delete('link');
  }

  return response;
};

export const handle = sequence(paraglideHandle, authHandle, headerFilterHandle);

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
  const startTime = performance.now();

  if (
    env.INTRIC_BACKEND_SERVER_URL &&
    env.INTRIC_BACKEND_URL &&
    request.url.startsWith(env.INTRIC_BACKEND_URL)
  ) {
    const originalUrl = request.url;
    const rewrittenUrl = request.url.replace(env.INTRIC_BACKEND_URL, env.INTRIC_BACKEND_SERVER_URL);

    console.log(`[handleFetch] Rewriting backend URL: ${originalUrl} -> ${rewrittenUrl}`);

    request = new Request(rewrittenUrl, request);

    try {
      const response = await fetch(request);
      const duration = Math.round(performance.now() - startTime);

      console.log(`[handleFetch] Response: ${response.status} ${response.statusText} (${duration}ms)`);

      if (duration > 5000) {
        console.warn(`[handleFetch] Slow response: ${duration}ms for ${rewrittenUrl}`);
      }

      return response;
    } catch (error) {
      const duration = Math.round(performance.now() - startTime);
      console.error(`[handleFetch] Fetch failed after ${duration}ms:`, {
        url: rewrittenUrl,
        error: error instanceof Error ? error.message : String(error)
      });
      throw error;
    }
  }

  return fetch(request);
};
