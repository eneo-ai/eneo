import { Suspense } from "react";
import { pageTitle } from "@/lib/page-metadata";
import { FlowChat } from "./flow-chat.client";

type Props = { params: Promise<{ spaceId: string; flowId: string }> };

export const generateMetadata = pageTitle("flows");

/**
 * A flow's page: the chat with the space's flow-authoring assistant, bound
 * to the flow's own conversation, with the panel showing the flow. `new`
 * starts a flow that is not created yet; the first `create_flow` call binds
 * the page to it and the address follows.
 */
export default async function FlowRoute({ params }: Props) {
  const { flowId } = await params;
  return (
    // useSearchParams (the `?run=` deep link) needs a suspense boundary during prerendering.
    <Suspense>
      <FlowChat flowId={flowId === "new" ? null : flowId} />
    </Suspense>
  );
}
