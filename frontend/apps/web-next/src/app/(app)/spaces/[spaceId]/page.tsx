import { redirect } from "next/navigation";

export default async function SpaceIndexPage({ params }: { params: Promise<{ spaceId: string }> }) {
  const { spaceId } = await params;
  // The personal space lands on its chat; everything else on the overview.
  redirect(spaceId === "personal" ? `/spaces/personal/chat` : `/spaces/${spaceId}/overview`);
}
