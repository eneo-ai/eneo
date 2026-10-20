"use client";

import { IconButton } from "@astryxdesign/core/IconButton";
import { Popover } from "@astryxdesign/core/Popover";
import {
  ArrowLeft,
  ChevronDown,
  Maximize2,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  X
} from "lucide-react";
import { useTranslations } from "next-intl";
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

/**
 * The frame's layout toggle. `cover`: the panel covers the conversation
 * (maximise, restore). `companion`: the panel is the page's main column and
 * the toggle folds the conversation beside it away (`on`) or shows it;
 * `controls` is the conversation column's id.
 */
export type PanelMaximise = {
  on: boolean;
  toggle: () => void;
  kind?: "cover" | "companion";
  controls?: string;
};

/** The level of the frame's title: 1 where the panel is the page's main column. */
export type PanelHeadingLevel = 1 | 2;

/**
 * The title of what the panel shows, with a line of detail beneath it. When
 * the conversation has more to show the two are also the switcher: one button
 * that opens the list of views, files and the latest activity, and a choice
 * from it takes the panel.
 */
function PanelTitle({
  title,
  detail,
  switcher,
  headingLevel
}: {
  title: string;
  detail?: string;
  switcher: PanelSwitcher | null;
  headingLevel: PanelHeadingLevel;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const count = switcher ? panelContentsCount(switcher.contents) + (switcher.activity ? 1 : 0) : 0;
  const Heading = headingLevel === 1 ? "h1" : "h2";

  if (!switcher || count < 2) {
    return (
      <>
        <Heading className="truncate text-sm font-semibold" title={title}>
          {title}
        </Heading>
        {detail && <p className="text-ax-text-secondary truncate text-xs tabular-nums">{detail}</p>}
      </>
    );
  }

  const choose = (show: () => void) => {
    setOpen(false);
    show();
  };

  return (
    // The popover wraps its trigger in an inline-flex anchor that sizes to
    // the button's content and clips the negative margins; letting the anchor
    // fill the title column (and the button fill the anchor) keeps the whole
    // title readable and gives the trigger the full column as its target.
    <Heading className="flex min-w-0 [&>div]:flex [&>div]:min-w-0 [&>div]:flex-1">
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
          className="hover:bg-ax-hover focus-visible:outline-ring rounded-ax-inner aria-expanded:bg-ax-hover -mx-2 -my-1 flex w-full min-w-0 flex-col items-start px-2 py-1 text-start focus-visible:outline-2 focus-visible:outline-offset-2"
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
    </Heading>
  );
}

/**
 * The frame every occupant of the side panel is shown in: a header with a
 * tile, the title (the switcher), the occupant's own actions, the layout
 * toggle and close, then the occupant's content.
 */
export function PanelFrame({
  icon,
  tileClassName,
  title,
  detail,
  status,
  actions,
  switcher,
  maximise,
  back,
  onClose,
  closeLabel,
  headingLevel = 2,
  children
}: {
  icon: ReactNode;
  tileClassName?: string;
  title: string;
  detail?: string;
  /** A line under the title that says what is going on (being written, an older version). */
  status?: ReactNode;
  actions?: ReactNode;
  switcher: PanelSwitcher | null;
  /** Null where there is nothing to maximise over (a sheet over the conversation). */
  maximise: PanelMaximise | null;
  /** Where closing this leads back to (the flow panel under a file), as a control before the tile. */
  back?: { label: string; onBack: () => void } | null;
  /** Absent where the occupant is the page itself and cannot be closed. */
  onClose?: () => void;
  closeLabel?: string;
  /** 1 where the panel is the page's main column: its title is the page's h1. */
  headingLevel?: PanelHeadingLevel;
  children: ReactNode;
}) {
  const t = useTranslations();
  const companion = maximise?.kind === "companion";
  const toggle = !maximise
    ? null
    : companion
      ? maximise.on
        ? { label: t("chat_companion_show"), icon: <PanelRightOpen className="size-4" /> }
        : { label: t("chat_companion_hide"), icon: <PanelRightClose className="size-4" /> }
      : maximise.on
        ? { label: t("file_preview_restore_size"), icon: <Minimize2 className="size-4" /> }
        : { label: t("file_preview_maximise"), icon: <Maximize2 className="size-4" /> };
  return (
    <>
      <header className="border-ax-border flex min-h-14 shrink-0 items-center gap-2.5 border-b py-2 ps-4 pe-2.5">
        {back && (
          <IconButton
            label={back.label}
            tooltip={back.label}
            icon={<ArrowLeft className="size-4" />}
            variant="ghost"
            size="sm"
            className="-ms-2"
            onClick={back.onBack}
          />
        )}
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
          <PanelTitle
            title={title}
            detail={detail}
            switcher={switcher}
            headingLevel={headingLevel}
          />
          {status}
        </div>
        {actions}
        {maximise && toggle && (
          <IconButton
            label={toggle.label}
            tooltip={toggle.label}
            icon={toggle.icon}
            variant="ghost"
            size="sm"
            aria-expanded={companion ? !maximise.on : undefined}
            aria-controls={companion && !maximise.on ? maximise.controls : undefined}
            onClick={maximise.toggle}
          />
        )}
        {onClose && (
          <IconButton
            label={closeLabel ?? t("close")}
            tooltip={closeLabel ?? t("close")}
            icon={<X className="size-4" />}
            variant="ghost"
            size="sm"
            onClick={onClose}
          />
        )}
      </header>
      {children}
    </>
  );
}
