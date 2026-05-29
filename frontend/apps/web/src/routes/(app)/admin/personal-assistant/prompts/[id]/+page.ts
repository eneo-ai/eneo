/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { redirect } from "@sveltejs/kit";
import { resolve } from "$app/paths";

export const load = ({ params }) => {
  throw redirect(307, resolve(`/admin/prompt-library/${params.id}`));
};
