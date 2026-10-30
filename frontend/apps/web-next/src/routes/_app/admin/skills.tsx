import { createFileRoute } from "@tanstack/react-router";
import { AdminSkillsPage } from "@/features/admin/skills/admin-skills-page";
import { routeTitle } from "@/lib/route-head";

export const Route = createFileRoute("/_app/admin/skills")({
  head: routeTitle("admin_skills_page_title"),
  component: AdminSkillsPage
});
