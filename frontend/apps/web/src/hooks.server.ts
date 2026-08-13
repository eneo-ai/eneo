import { dev } from "$app/environment";
import { DASHBOARD_URL } from "$lib/core/constants";
import { detectMobile } from "$lib/core/detectMobile";
import { getFeatureFlags } from "$lib/core/flags.server";
import { authenticateUser, clearFrontendCookies } from "$lib/features/auth/auth.server";
import { ENEO_RESPONSE_HEADERS } from "@eneo/eneo-js";
import { toAppError } from "$lib/core/errors";
import { redirect, type Handle, type HandleFetch, type HandleServerError } from "@sveltejs/kit";
import {
  getEnvironmentConfig,
  getBackendUrl,
  getBackendServerUrl
} from "./lib/core/environment.server";
import { fetchWithTransientRetry } from "./lib/core/transientFetch.server";
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

export const headerFilterHandle: Handle = async ({ event, resolve }) => {
  const response = await resolve(event, {
    preload: () => false,
    // Responses fetched inside a load function have their headers stripped
    // unless listed here. The Eneo client reads the trace id and error code off
    // failed responses (see ENEO_RESPONSE_HEADERS); without this, every API
    // failure during SSR turns into a "Failed to get response header" error
    // that hides the real one.
    filterSerializedResponseHeaders: (name) => ENEO_RESPONSE_HEADERS.includes(name)
  });
  return response;
};

export const handle = sequence(paraglideHandle, authHandle, headerFilterHandle);

export const handleError: HandleServerError = async ({ error, event, status, message }) => {
  const appError = toAppError(error, { status, message });

  // SvelteKit stops logging errors itself once this hook exists, so without
  // this a production 500 leaves nothing behind on the server. Log what ties
  // the failure to the backend — never the request payload or response body.
  const report = {
    route: event.route.id ?? event.url.pathname,
    ...appError,
    stack: error instanceof Error ? error.stack : undefined
  };
  console.error("server error", dev ? { ...report, error } : report);

  return appError;
};

export const handleFetch: HandleFetch = async ({ request, fetch }) => {
  const serverUrl = getBackendServerUrl();
  const backendUrl = getBackendUrl();

  if (serverUrl && backendUrl && request.url.startsWith(backendUrl)) {
    request = new Request(request.url.replace(backendUrl, serverUrl), request);
  }

  return fetchWithTransientRetry(request, fetch);
};
