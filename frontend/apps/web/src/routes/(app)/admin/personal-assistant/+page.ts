/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";

export const load = async () => {
  redirect(302, resolve("/admin/personal-assistant/configuration"));
};
