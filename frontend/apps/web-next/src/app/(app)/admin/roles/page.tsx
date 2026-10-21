import { redirect } from "next/navigation";
import { pageTitle } from "@/lib/page-metadata";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { RolesPage } from "@/features/admin/roles/roles-page";

export const generateMetadata = pageTitle("roles");

export default async function AdminRolesRoute() {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("admin")) redirect("/admin");
  return <RolesPage />;
}
