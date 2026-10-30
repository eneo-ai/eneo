import { fail, redirect, type RequestEvent } from "@sveltejs/kit";
import { clearFrontendCookies } from "./auth.server";
import {
  changePassword,
  discoverPasswordChangeCapability,
  PasswordChangeRequestError
} from "./passwordChange.server";
import {
  validatePasswordChange,
  type PasswordChangeActionFailure,
  type PasswordChangeCapability,
  type PasswordFieldErrors
} from "./passwordChange";

type RequestContext = ReturnType<typeof passwordRequestContext>;

export function passwordRequestContext(event: RequestEvent) {
  return {
    backendUrl: event.locals.environment.baseUrl,
    eneoToken: event.locals.id_token,
    zitadelUrl: event.locals.environment.authUrl,
    zitadelToken: event.locals.access_token,
    fetch: event.fetch
  };
}

function formString(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

function actionFailureFor(error: PasswordChangeRequestError): PasswordChangeActionFailure {
  const fieldErrors: PasswordFieldErrors = {};
  if (error.reason === "current_password_incorrect") {
    fieldErrors.currentPassword = "current_password_incorrect";
    return { fieldErrors };
  }
  if (error.reason === "password_unchanged") {
    fieldErrors.newPassword = "password_unchanged";
    return { fieldErrors };
  }
  if (error.reason === "policy_rejected") {
    fieldErrors.newPassword = "policy_rejected";
    return { fieldErrors };
  }
  if (error.reason === "not_available") return { formError: "not_available" };
  if (error.reason === "provider_rejected") return { formError: "provider_rejected" };
  if (error.reason === "rate_limited") return { formError: "rate_limited" };
  return { formError: "request_failed" };
}

/**
 * Change the signed-in user's password from a posted form, then sign this
 * browser out so the new credential version takes effect everywhere.
 *
 * `resolveCapability` decides which credential is changed: the account page
 * follows the login provider, the forced-change page always targets the local
 * Eneo password. `nextDestination`, when given, is carried to the login page.
 */
export async function runPasswordChangeAction(
  event: RequestEvent,
  {
    nextDestination = null,
    resolveCapability = discoverPasswordChangeCapability
  }: {
    nextDestination?: string | null;
    resolveCapability?: (context: RequestContext) => Promise<PasswordChangeCapability>;
  } = {}
) {
  const data = await event.request.formData();
  const values = {
    currentPassword: formString(data, "currentPassword"),
    newPassword: formString(data, "newPassword"),
    confirmPassword: formString(data, "confirmPassword")
  };
  const context = passwordRequestContext(event);
  const capability = await resolveCapability(context);

  if (capability.source === "external" || capability.source === "unavailable") {
    return fail(409, {
      passwordChange: { formError: "not_available" } satisfies PasswordChangeActionFailure
    });
  }

  const fieldErrors = validatePasswordChange(values, capability);
  if (Object.keys(fieldErrors).length > 0) {
    return fail(400, {
      passwordChange: { fieldErrors } satisfies PasswordChangeActionFailure
    });
  }

  let result;
  try {
    result = await changePassword(context, capability, values.currentPassword, values.newPassword);
  } catch (error) {
    if (error instanceof PasswordChangeRequestError) {
      const status = error.status >= 400 && error.status < 600 ? error.status : 500;
      return fail(status, { passwordChange: actionFailureFor(error) });
    }
    return fail(500, {
      passwordChange: { formError: "request_failed" } satisfies PasswordChangeActionFailure
    });
  }

  clearFrontendCookies(event);
  const message =
    result === "session_invalidation_failed"
      ? "password_changed_sessions_remain"
      : "password_changed";
  const params = new URLSearchParams({ message });
  if (nextDestination) params.set("next", nextDestination);
  redirect(303, `/login?${params.toString()}`);
}
