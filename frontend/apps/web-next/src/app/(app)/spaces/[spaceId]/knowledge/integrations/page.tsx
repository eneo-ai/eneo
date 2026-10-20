import { redirect } from "next/navigation";

/** The parent of the source pages; the integrations themselves are a tab of the knowledge page. */
export default async function IntegrationsPage({
  params
}: {
  params: Promise<{ spaceId: string }>;
}) {
  const { spaceId } = await params;
  redirect(`/spaces/${spaceId}/knowledge?tab=integrations`);
}
