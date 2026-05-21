/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { redirect } from "@sveltejs/kit";

export const load = async () => {
  redirect(302, "/admin/personal-chat/configuration");
};
