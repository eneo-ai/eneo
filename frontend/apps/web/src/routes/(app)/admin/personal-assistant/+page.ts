/*
    Copyright (c) 2026 Sundsvalls Kommun
*/

import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";

export const load = async () => {
  redirect(302, resolve("/admin/personal-assistant/configuration"));
};
