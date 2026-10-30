import { Suspense } from "react";
import { SpaceChat } from "@/features/spaces/chat/space-chat.client";

export default function SpaceChatPage() {
  return (
    // useSearchParams requires a suspense boundary during prerendering.
    <Suspense>
      <SpaceChat />
    </Suspense>
  );
}
