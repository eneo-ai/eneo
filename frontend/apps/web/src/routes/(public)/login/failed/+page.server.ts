import { LoginError } from "$lib/features/auth/LoginError.js";
import { resolveSafeLoginDestination } from "$lib/features/auth/auth.server";

export const load = async (event) => {
  const message = event.url.searchParams.get("message") ?? "Unknown failure. No message received.";
  const errorInfo = event.url.searchParams.get("info");
  const details = event.url.searchParams.get("details");
  const requestedDestination = event.url.searchParams.get("next");
  const retryUrl =
    requestedDestination === null
      ? "/login"
      : `/login?${new URLSearchParams({
          next: resolveSafeLoginDestination(requestedDestination)
        }).toString()}`;

  // Map error messages to user-friendly text
  let userMessage = "";

  if (message === "zitadel_login_error") {
    userMessage = "Authentication failed. Please check your credentials and try again.";
  } else if (message === "no_code_received") {
    userMessage = "Authentication was incomplete. No authorization code was received.";
  } else if (message === "no_state_received") {
    userMessage = "Authentication was incomplete. Security validation failed.";
  } else if (errorInfo) {
    userMessage = LoginError.getMessageFromShortCode(errorInfo);
  } else {
    userMessage = message;
  }

  return {
    message: userMessage,
    details: details ? decodeURIComponent(details) : null,
    retryUrl
  };
};
