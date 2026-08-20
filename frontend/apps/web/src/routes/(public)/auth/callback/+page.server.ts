// Tenant federation may still be configured with /auth/callback. Keep that
// public URL, but use the same validated exchange and resume owner as the
// canonical /login/callback route.
export { load } from "../../login/callback/+page.server";
