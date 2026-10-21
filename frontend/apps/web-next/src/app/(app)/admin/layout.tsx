import { redirect } from "next/navigation";
import { unwrap } from "@/lib/api/errors";
import { eneoApi } from "@/lib/api/server";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";

/** Admin pages inherit "Administration · Eneo" unless they set their own title. */
export const generateMetadata = pageTitle("shell_administration");

/**
 * Admin area gate. The admin navigation lives in the app shell's SideNav
 * (admin mode under /admin), where it is hidden without the admin permission;
 * this is the real client-visible guard: non-admins are redirected home. (The
 * backend is the true authority — every org call fails without super-user
 * rights.)
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("admin")) redirect("/");

  // The page panel (main) scrolls; this only pads the admin pages.
  return <div className="flex min-w-0 flex-1 flex-col p-4 sm:p-6">{children}</div>;
}
