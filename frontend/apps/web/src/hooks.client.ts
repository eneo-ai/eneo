import { toAppError } from "$lib/core/errors";
import type { HandleClientError } from "@sveltejs/kit";

export const handleError: HandleClientError = async ({ error, status, message }) => {
  const appError = toAppError(error, { status, message });

  // Surface the backend trace ID so users can pass it to support and it shows
  // up in any client-side error report consuming console output.
  console.error("client error", appError, error);

  return appError;
};
