import { redirect } from "next/navigation";
import { unwrap } from "@/lib/api/errors";
import { eneoApi } from "@/lib/api/server";
import { hasPermission } from "@/lib/auth/permissions";
import { pageTitle } from "@/lib/page-metadata";
import { AdminNav } from "./admin-nav.client";

/** Admin pages inherit "Admin · Eneo" unless they set their own title. */
export const generateMetadata = pageTitle("admin");

/**
 * Admin area gate. The nav is hidden without the admin permission, but this is
 * the real client-visible guard: non-admins are redirected home. (The backend
 * is the true authority — every org call fails without super-user rights.)
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("admin")) redirect("/");

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="bg-sidebar hidden w-60 shrink-0 overflow-y-auto border-r p-3 md:block">
        <AdminNav />
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto p-6">{children}</div>
    </div>
  );
}
