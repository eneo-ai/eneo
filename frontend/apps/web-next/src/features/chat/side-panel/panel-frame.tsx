"use client";

import { IconButton } from "@astryxdesign/core/IconButton";
import { Popover } from "@astryxdesign/core/Popover";
import { ChevronDown, Maximize2, Minimize2, X } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { PreviewFile } from "@/features/workspace/preview/preview-kind";
import type { PanelContents, PanelView } from "./panel-contents";
import { panelContentsCount } from "./panel-contents";
import { PanelContentsList, type ActivityEntry } from "./panel-contents-list";
import type { SidePanelStore } from "./side-panel-store";

/** Everything the panel's title can switch to. */
export type PanelSwitcher = {
  panel: SidePanelStore;
  contents: PanelContents;
  activity: ActivityEntry | null;
  onFile: (file: PreviewFile) => void;
  onView: (view: PanelView) => void;
};

export type PanelMaximise = { on: boolean; toggle: () => void };

/**
 * The title of what the panel shows, with a line of detail beneath it. When
 * the conversation has more to show the two are also the switcher: one button
 * that opens the list of views, files and the latest activity, and a choice
 * from it takes the panel.
 */
function PanelTitle({
  title,
  detail,
  switcher
}: {
  title: string;
  detail?: string;
  switcher: PanelSwitcher | null;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const count = switcher ? panelContentsCount(switcher.contents) + (switcher.activity ? 1 : 0) : 0;

  if (!switcher || count < 2) {
    return (
      <>
        <h2 className="truncate text-sm font-semibold" title={title}>
          {title}
        </h2>
        {detail && <p className="text-ax-text-secondary truncate text-xs tabular-nums">{detail}</p>}
      </>
    );
  }

  const choose = (show: () => void) => {
    setOpen(false);
    show();
  };

  return (
    <h2 className="flex min-w-0">
      <Popover
        isOpen={open}
        onOpenChange={setOpen}
        label={t("panel_switcher_heading")}
        placement="below"
        alignment="start"
        width={320}
        content={
          // The popover sizes and scrolls its own surface; a width of its own
          // here would overflow the padding and bring scrollbars.
          <div className="flex min-w-0 flex-col">
            <PanelContentsList
              panel={switcher.panel}
              contents={switcher.contents}
              activity={switcher.activity}
              onFile={(file) => choose(() => switcher.onFile(file))}
              onView={(view) => choose(() => switcher.onView(view))}
            />
          </div>
        }
      >
        <button
          type="button"
          aria-label={`${title}. ${t("panel_switcher_hint")}`}
          title={title}
          className="hover:bg-ax-hover focus-visible:outline-ring rounded-ax-inner aria-expanded:bg-ax-hover -mx-2 -my-1 flex max-w-full min-w-0 flex-col items-start px-2 py-1 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          <span className="flex max-w-full min-w-0 items-center gap-1">
            <span className="truncate text-sm font-semibold">{title}</span>
            <ChevronDown aria-hidden="true" className="text-ax-text-secondary size-3.5 shrink-0" />
          </span>
          {detail && (
            <span className="text-ax-text-secondary max-w-full truncate text-xs font-normal tabular-nums">
              {detail}
            </span>
          )}
        </button>
      </Popover>
    </h2>
  );
}

/**
 * The frame every occupant of the side panel is shown in: a header with a
 * tile, the title (the switcher), the occupant's own actions, maximise and
 * close, then the occupant's content.
 */
export function PanelFrame({
  icon,
  tileClassName,
  title,
  detail,
  status,
  actions,
  toolbar,
  switcher,
  maximise,
  onClose,
  closeLabel,
  children
}: {
  icon: ReactNode;
  tileClassName?: string;
  title: string;
  detail?: string;
  /** A line under the title that says what is going on (being written, an older version). */
  status?: ReactNode;
  actions?: ReactNode;
  /**
   * A row of the occupant's own beneath the header (a document's versions and
   * export, or its save bar). It draws the border the header otherwise has, so
   * the title keeps its width whatever the occupant can do.
   */
  toolbar?: ReactNode;
  switcher: PanelSwitcher | null;
  /** Null where there is nothing to maximise over (a sheet over the conversation). */
  maximise: PanelMaximise | null;
  onClose: () => void;
  closeLabel?: string;
  children: ReactNode;
}) {
  const t = useTranslations();
  return (
    <>
      <header
        className={cn(
          "border-ax-border flex min-h-14 shrink-0 items-center gap-2.5 py-2 ps-4 pe-2.5",
          !toolbar && "border-b"
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "rounded-ax-inner flex size-8 shrink-0 items-center justify-center",
            tileClassName ?? "bg-ax-accent-muted text-ax-text-accent"
          )}
        >
          {icon}
        </span>
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <PanelTitle title={title} detail={detail} switcher={switcher} />
          {status}
        </div>
        {actions}
        {maximise && (
          <IconButton
            label={maximise.on ? t("file_preview_restore_size") : t("file_preview_maximise")}
            tooltip={maximise.on ? t("file_preview_restore_size") : t("file_preview_maximise")}
            icon={maximise.on ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
            variant="ghost"
            size="sm"
            onClick={maximise.toggle}
          />
        )}
        <IconButton
          label={closeLabel ?? t("close")}
          tooltip={closeLabel ?? t("close")}
          icon={<X className="size-4" />}
          variant="ghost"
          size="sm"
          onClick={onClose}
        />
      </header>
      {toolbar}
      {children}
    </>
  );
}
