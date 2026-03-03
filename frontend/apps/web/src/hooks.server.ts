import { dev } from "$app/environment";
import { DASHBOARD_URL } from "$lib/core/constants";
import { detectMobile } from "$lib/core/detectMobile";
import { getFeatureFlags } from "$lib/core/flags.server";
import { authenticateUser, clearFrontendCookies } from "$lib/features/auth/auth.server";
import { IntricError, type IntricErrorCode } from "@intric/intric-js";
import { redirect, type Handle, type HandleFetch, type HandleServerError } from "@sveltejs/kit";
import { getEnvironmentConfig, getBackendUrl, getBackendServerUrl } from "./lib/core/environment.server";
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

  // Load feature flags and environment BEFORE authentication check
  // This ensures login page has access to federation configuration flags
  // Pass event.fetch so URL rewriting in handleFetch works correctly
  event.locals.featureFlags = await getFeatureFlags(event.fetch);
  event.locals.environment = getEnvironmentConfig();

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
  const response = await resolve(event, {
    preload: () => false,
  });
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
  const serverUrl = getBackendServerUrl();
  const backendUrl = getBackendUrl();

  if (serverUrl && backendUrl && request.url.startsWith(backendUrl)) {
    request = new Request(
      request.url.replace(backendUrl, serverUrl),
      request
    );
  }

  return fetch(request);
};
