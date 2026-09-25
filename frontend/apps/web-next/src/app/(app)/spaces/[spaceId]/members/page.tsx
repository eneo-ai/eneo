import { pageTitle } from "@/lib/page-metadata";
import { SpaceMembers } from "@/features/spaces/members/space-members";

export const generateMetadata = pageTitle("members");

export default function SpaceMembersPage() {
  return <SpaceMembers />;
}
