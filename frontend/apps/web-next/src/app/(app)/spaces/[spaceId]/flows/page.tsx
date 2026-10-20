import { redirect } from "next/navigation";
import { FlowsPage } from "@/features/flows/flows-page";
import { pageTitle } from "@/lib/page-metadata";

type Props = { params: Promise<{ spaceId: string }> };

// The space layout's title template adds the space name: "Flöden · Upphandling · Eneo".
export const generateMetadata = pageTitle("flows");

export default async function FlowsRoute({ params }: Props) {
  const { spaceId } = await params;
  // Flows belong to a space's work; the organization space has none.
  if (spaceId === "organization") redirect("/spaces/organization/knowledge");
  return <FlowsPage />;
}
