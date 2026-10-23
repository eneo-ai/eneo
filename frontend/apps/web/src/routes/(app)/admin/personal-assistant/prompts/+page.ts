/*
    Copyright (c) 2026 Sundsvalls Kommun
*/

import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";

export const load = () => {
  throw redirect(307, resolve("/admin/prompt-library"));
};
