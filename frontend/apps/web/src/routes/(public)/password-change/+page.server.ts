import { redirect } from "@sveltejs/kit";
import { resolveSafeLoginDestination } from "$lib/features/auth/auth.server";
import { discoverLocalPasswordState } from "$lib/features/auth/passwordChange.server";
import {
  passwordRequestContext,
  runPasswordChangeAction
} from "$lib/features/auth/passwordChangeAction.server";
import { PASSWORD_CHANGE_PATH } from "$lib/features/auth/passwordChangeRequired";
import type { Actions, PageServerLoad } from "./$types";

function requestedDestination(url: URL): string | null {
  const next = url.searchParams.get("next");
  return next === null ? null : resolveSafeLoginDestination(next);
}

/**
 * A signed-in user whose one-time or expired password blocks every other
 * endpoint lands here. Outside the app shell on purpose: that shell loads
 * data the backend refuses until the password has been replaced.
 */
export const load: PageServerLoad = async (event) => {
  if (!event.locals.id_token) {
    const resume = PASSWORD_CHANGE_PATH + event.url.search;
    redirect(302, `/login?next=${encodeURIComponent(resume)}`);
  }

  const state = await discoverLocalPasswordState(passwordRequestContext(event));
  if (state.changeReason === null) {
    redirect(302, resolveSafeLoginDestination(requestedDestination(event.url)));
  }

  return {
    capability: state.capability,
    reason: state.changeReason,
    username: state.username ?? "",
    next: requestedDestination(event.url)
  };
};

export const actions: Actions = {
  changePassword: (event) => runPasswordChangeAction(event, requestedDestination(event.url))
};
