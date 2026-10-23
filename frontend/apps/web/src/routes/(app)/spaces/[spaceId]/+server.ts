/*
    Copyright (c) 2024 Sundsvalls Kommun
*/

import { redirect } from "@sveltejs/kit";

export const GET = async (event) => {
  // If we're landing on the space directly, forward to default assistant if it's the personal space
  if (event.url.pathname === "/spaces/personal") {
    redirect(302, event.url.pathname + "/chat");
  }
  // Otherwise forward to the overview
  redirect(302, event.url.pathname + "/overview");
};
