import { redirect } from "next/navigation";
import { pageTitle } from "@/lib/page-metadata";
import { eneoApi } from "@/lib/api/server";
import { unwrap } from "@/lib/api/errors";
import { hasPermission } from "@/lib/auth/permissions";
import { AdminSkillsPage } from "@/features/admin/skills/admin-skills-page";

export const generateMetadata = pageTitle("admin_skills_page_title");

export default async function AdminSkillsRoute() {
  const user = await unwrap(eneoApi().GET("/api/v1/users/me/"));
  if (!hasPermission(user)("admin")) redirect("/admin");
  return <AdminSkillsPage />;
}
