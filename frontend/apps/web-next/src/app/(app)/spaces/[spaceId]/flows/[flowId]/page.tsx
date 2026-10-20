import { redirect } from "next/navigation";
import { Suspense } from "react";
import { pageTitle } from "@/lib/page-metadata";
import { FlowChat } from "./flow-chat.client";

type Props = { params: Promise<{ spaceId: string; flowId: string }> };

export const generateMetadata = pageTitle("flows");

/**
 * A flow's page: the chat with the space's flow-authoring assistant, bound
 * to the flow's own conversation, with the panel showing the flow.
 */
export default async function FlowRoute({ params }: Props) {
  const { spaceId, flowId } = await params;
  // A flow exists before its chat: "Nytt flöde" on the list creates the draft.
  if (flowId === "new") redirect(`/spaces/${spaceId}/flows`);
  return (
    // useSearchParams (the `?run=` deep link) needs a suspense boundary during prerendering.
    <Suspense>
      <FlowChat flowId={flowId} />
    </Suspense>
  );
}
