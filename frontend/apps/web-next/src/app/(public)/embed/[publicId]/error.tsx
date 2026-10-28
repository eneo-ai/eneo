"use client";

import { WidgetNotice } from "@/features/widget/components/widget-unavailable";

/** The backend did not answer: the same notice as for a paused widget, framed or not. */
export default function EmbedError() {
  return <WidgetNotice hostOrigin={null} />;
}
