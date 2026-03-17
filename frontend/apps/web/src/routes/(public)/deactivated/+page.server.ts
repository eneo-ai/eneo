import { getBackendUrl } from "$lib/core/environment.server";
import { DEFAULT_LANDING_PAGE } from "$lib/core/constants.js";
import { redirect } from "@sveltejs/kit";

export const load = async (event) => {
  const accessToken = event.locals.access_token;

  // If user is not even logged in (=no token found), we redirect to login page instead
  if (!accessToken) {
    redirect(302, "/login");
  }

  const response = await event.fetch(getBackendUrl() + "/api/v1/users/me", {
    headers: {
      Authorization: `Bearer ${accessToken}`
    }
  });

  // If the user can access their profile, the organization is no longer deactivated
  if (response.ok) {
    redirect(302, DEFAULT_LANDING_PAGE);
  }

  // Otherwise show the deactivated page
  return {
    salesEmail: event.locals.environment.salesEmail
  };
};
