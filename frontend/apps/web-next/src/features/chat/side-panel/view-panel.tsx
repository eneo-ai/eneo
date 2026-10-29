"use client";

import { AppWindow } from "lucide-react";
import { useTranslations } from "use-intl";
import { useCallback } from "react";
import { appViewSubject, appViewTitle, type McpAppCall } from "@/features/mcp-apps/mcp-apps";
import { PanelFrame, type PanelMaximise, type PanelSwitcher } from "./panel-frame";
import type { SidePanelStore } from "./side-panel-store";

/**
 * An interactive tool view beside the conversation. The view's frame stays
 * mounted in its message; this is its layout anchor, and the header that
 * names it as its call does (what it is about, above the tool it belongs to).
 */
export function ViewPanel({
  panel,
  call,
  switcher,
  maximise
}: {
  panel: SidePanelStore;
  call: McpAppCall;
  switcher: PanelSwitcher | null;
  maximise: PanelMaximise | null;
}) {
  const t = useTranslations();
  const tool = appViewTitle(call, t);
  const subject = appViewSubject(call);
  // Closing a view that covers a file brings the file back; the button says so.
  const covered = panel.file?.name || panel.draft?.title || null;
  const anchor = useCallback(
    (element: HTMLDivElement | null) => panel.setViewTarget(element),
    [panel]
  );

  return (
    <PanelFrame
      icon={<AppWindow className="size-4" />}
      tileClassName="bg-ax-teal-muted text-ax-teal"
      title={subject ?? tool}
      detail={subject ? tool : t("mcp_app_view_title")}
      switcher={switcher}
      maximise={maximise}
      onClose={() => panel.dismissView()}
      closeLabel={covered ? t("mcp_app_view_close_to_file", { name: covered }) : t("close")}
    >
      <div ref={anchor} className="min-h-0 flex-1" />
    </PanelFrame>
  );
}
