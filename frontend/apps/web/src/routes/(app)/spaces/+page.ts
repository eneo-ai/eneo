/*
    Copyright (c) 2024 Sundsvalls Kommun
*/

import { redirect } from "@sveltejs/kit";

export const load = async () => {
  redirect(302, "/spaces/list");
};
