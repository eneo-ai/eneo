import { discoverPasswordChangeCapability } from "$lib/features/auth/passwordChange.server";
import {
  passwordRequestContext,
  runPasswordChangeAction
} from "$lib/features/auth/passwordChangeAction.server";
import type { Actions, PageServerLoad } from "./$types";

export const load: PageServerLoad = async (event) => ({
  passwordChangeCapability: await discoverPasswordChangeCapability(passwordRequestContext(event))
});

export const actions: Actions = {
  changePassword: (event) => runPasswordChangeAction(event)
};
