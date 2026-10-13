import { Suspense } from "react";
import { SpaceChat } from "./space-chat.client";

export default function SpaceChatPage() {
  return (
    // useSearchParams requires a suspense boundary during prerendering.
    <Suspense>
      <SpaceChat />
    </Suspense>
  );
}
