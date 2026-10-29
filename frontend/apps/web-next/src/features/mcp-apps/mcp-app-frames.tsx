"use client";

import { useTranslations } from "use-intl";
import { lazy, Suspense, useState, type ComponentType } from "react";
import type { EneoUIMessage } from "@/lib/chat/types";
import { messageAppViewCalls, type McpAppCall } from "./mcp-apps";
import { McpAppViewNote, McpAppViewSkeleton, unsizedHeight } from "./mcp-app-placeholder";
import { useViewLink, type ViewLink, type ViewLinkError } from "./use-view-link";

type FrameProps = {
  call: McpAppCall;
  live: boolean;
  startedLive: boolean;
  sessionId: string | null;
  link: ViewLink | null;
  linkError: ViewLinkError | null;
};

function McpAppFrameUnavailable() {
  const t = useTranslations();
  return <McpAppViewNote>{t("mcp_app_view_unavailable_generic")}</McpAppViewNote>;
}

// The frame and the MCP app bridge load with the first answer that has a view,
// not with every chat. A failed load (its chunk gone after a deploy) says the
// view is unavailable, and the next view to appear tries again.
const lazyFrame = (): ComponentType<FrameProps> =>
  lazy(() =>
    import("./mcp-app-frame").then(
      (module) => ({ default: module.McpAppFrame }),
      () => {
        LazyMcpAppFrame = lazyFrame();
        return { default: McpAppFrameUnavailable };
      }
    )
  );
let LazyMcpAppFrame = lazyFrame();

/**
 * The interactive views of an answer: HTML an approved tool brings, shown in
 * a sandboxed frame under the answer. A view belongs to one tool call and is
 * there from the moment the model starts writing the call.
 */
export function McpAppFrames({
  message,
  live,
  sessionId
}: {
  message: EneoUIMessage;
  /** The answer is being written right now. */
  live: boolean;
  sessionId: string | null;
}) {
  const calls = messageAppViewCalls(message);
  if (calls.length === 0) return null;
  return (
    <>
      {calls.map((call) => (
        <McpAppCallView key={call.toolCallId} call={call} live={live} sessionId={sessionId} />
      ))}
    </>
  );
}

/**
 * One call's view, from the moment it appears, while the frame's code may
 * still be on its way. Fixed here when the view first renders: whether its
 * answer was being written (the view's starting height and how its frame
 * loads) and which frame code it waits for, so a view whose code failed keeps
 * its note through re-renders. Its link is minted meanwhile, not after.
 */
function McpAppCallView({
  call,
  live,
  sessionId
}: Pick<FrameProps, "call" | "live" | "sessionId">) {
  const [startedLive] = useState(live);
  const [Frame] = useState(() => LazyMcpAppFrame);
  const { link, error } = useViewLink(call.view.viewId);
  return (
    <Suspense fallback={<McpAppViewSkeleton height={unsizedHeight(startedLive)} inline />}>
      <Frame
        call={call}
        live={live}
        startedLive={startedLive}
        sessionId={sessionId}
        link={link}
        linkError={error}
      />
    </Suspense>
  );
}
