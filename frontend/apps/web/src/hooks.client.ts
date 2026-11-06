import { toAppError } from "$lib/core/errors";
import { isEmbedPage } from "$lib/features/widget/embedLanguage";
import { overwriteSetLocale } from "$lib/paraglide/runtime";
import type { HandleClientError } from "@sveltejs/kit";

// Paraglide's getLocale() saves the locale in a cookie on its first call in the
// browser, and the root layout's language store makes that call on every page.
// The embed page promises visitors no cookies, and its address carries the locale.
if (isEmbedPage(new URL(window.location.href))) overwriteSetLocale(() => {});

export const handleError: HandleClientError = async ({ error, status, message }) => {
  const appError = toAppError(error, { status, message });

  // Surface the backend trace ID so users can pass it to support and it shows
  // up in any client-side error report consuming console output.
  console.error("client error", appError, error);

  return appError;
};
