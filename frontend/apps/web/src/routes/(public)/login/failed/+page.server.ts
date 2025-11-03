import { LoginError } from "$lib/features/auth/LoginError.js";

export const load = async (event) => {
  const message = event.url.searchParams.get("message") ?? "Unknown failure. No message received.";
  const errorInfo = event.url.searchParams.get("info");
  const details = event.url.searchParams.get("details");

  // Map error messages to user-friendly text
  let userMessage = "";

  if (message === "mobilityguard_login_error") {
    userMessage = "Authentication failed. Please check your credentials and try again.";
  } else if (message === "zitadel_login_error") {
    userMessage = "Authentication failed. Please check your credentials and try again.";
  } else if (message === "no_code_received") {
    userMessage = "Authentication was incomplete. No authorization code was received.";
  } else if (message === "no_state_received") {
    userMessage = "Authentication was incomplete. Security validation failed.";
  } else if (message === "mobilityguard_oauth_error") {
    userMessage = "The authentication provider encountered an error. Please try again.";
  } else if (message === "mobilityguard_access_denied") {
    userMessage = "Access was denied. You may not have permission to access this application.";
  } else if (message === "mobilityguard_invalid_request") {
    userMessage =
      "The authentication request was invalid. Please clear your cookies and try again.";
  } else if (errorInfo) {
    userMessage = LoginError.getMessageFromShortCode(errorInfo);
  } else {
    userMessage = message;
  }

  return {
    message: userMessage,
    details: details ? decodeURIComponent(details) : null
  };
};
