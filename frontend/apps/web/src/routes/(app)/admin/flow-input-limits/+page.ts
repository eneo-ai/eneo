import { redirect } from "@sveltejs/kit";

// This page moved into the consolidated flow settings surface.
export const load = (event) => {
  const target = event.url.pathname.replace(/flow-input-limits$/, "flow-settings");
  redirect(301, `${target}?tab=uploads`);
};
