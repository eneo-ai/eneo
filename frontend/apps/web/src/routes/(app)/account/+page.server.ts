import { clearFrontendCookies } from "$lib/features/auth/auth.server";
import {
  changePassword,
  discoverPasswordChangeCapability,
  PasswordChangeRequestError
} from "$lib/features/auth/passwordChange.server";
import {
  validatePasswordChange,
  type PasswordChangeActionFailure,
  type PasswordFieldErrors
} from "$lib/features/auth/passwordChange";
import { fail, redirect, type RequestEvent } from "@sveltejs/kit";
import type { Actions, PageServerLoad } from "./$types";

function requestContext(event: RequestEvent) {
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

export const load: PageServerLoad = async (event) => ({
  passwordChangeCapability: await discoverPasswordChangeCapability(requestContext(event))
});

export const actions: Actions = {
  changePassword: async (event) => {
    const data = await event.request.formData();
    const values = {
      currentPassword: formString(data, "currentPassword"),
      newPassword: formString(data, "newPassword"),
      confirmPassword: formString(data, "confirmPassword")
    };
    const context = requestContext(event);
    const capability = await discoverPasswordChangeCapability(context);

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
      result = await changePassword(
        context,
        capability,
        values.currentPassword,
        values.newPassword
      );
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
    redirect(303, `/login?message=${message}`);
  }
};
