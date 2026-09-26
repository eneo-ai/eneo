"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { ActivitySource } from "./activity";
import { McpResourceSnippetDialog } from "./message-parts";

/** Id of the source entry that inline citation N (1-based) opens. */
export function sourceAnchorId(messageId: string, number: number): string {
  return `${messageId}-source-${number}`;
}

/**
 * The Aktivitet panel's Källor tab: an answer's numbered sources with where
 * they come from. A citation that opened the panel focuses its source.
 */
export function SourceList({
  messageId,
  sources,
  focusIndex
}: {
  messageId: string;
  sources: ActivitySource[];
  focusIndex: number | null;
}) {
  const t = useTranslations();
  const itemRefs = useRef<Map<number, HTMLLIElement>>(new Map());

  // A citation opened the panel: move focus to that source (WCAG 2.4.3). In
  // the bottom sheet this runs before the sheet's dialog opens (nothing in a
  // closed dialog takes focus); the sheet then focuses the item marked
  // data-autofocus instead.
  useEffect(() => {
    if (focusIndex === null) return;
    const item = itemRefs.current.get(focusIndex);
    item?.focus();
    item?.scrollIntoView({ block: "nearest" });
  }, [focusIndex, messageId]);

  if (sources.length === 0) {
    return (
      <p className="text-ax-text-secondary px-1 text-[13px]">{t("chat_activity_no_sources")}</p>
    );
  }

  return (
    <ol className="flex flex-col gap-1">
      {sources.map((source, index) => {
        const number = index + 1;
        const meta = [
          source.origin,
          source.pageRange ? t("mcp_resource_page_range", { pageRange: source.pageRange }) : null
        ]
          .filter(Boolean)
          .join(" · ");
        const titleClass =
          "focus-visible:outline-ring rounded-ax-inner text-left text-[13px] leading-snug font-medium break-words focus-visible:outline-2 focus-visible:outline-offset-2";
        return (
          <li
            key={source.key}
            id={sourceAnchorId(messageId, number)}
            ref={(element) => {
              if (element) itemRefs.current.set(index, element);
              else itemRefs.current.delete(index);
            }}
            tabIndex={-1}
            data-autofocus={index === focusIndex ? "" : undefined}
            className="focus-visible:outline-ring rounded-ax-element focus:bg-ax-selected flex gap-2.5 p-2 focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            <span
              aria-hidden="true"
              className="bg-ax-muted rounded-ax-inner mt-px flex size-5 shrink-0 items-center justify-center text-[11px] font-bold"
            >
              {number}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="sr-only">{t("chat_source_number", { number })}</span>
              {source.url ? (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(titleClass, "hover:underline")}
                >
                  {source.title}
                  <ExternalLink aria-hidden="true" className="ms-1 inline size-3 align-[-1px]" />
                  <span className="sr-only"> {t("chat_opens_in_new_tab")}</span>
                </a>
              ) : source.mcpSnippet ? (
                <McpResourceSnippetDialog source={source} snippet={source.mcpSnippet}>
                  <button type="button" className={cn(titleClass, "hover:underline")}>
                    {source.title}
                  </button>
                </McpResourceSnippetDialog>
              ) : (
                <span className="text-[13px] leading-snug font-medium break-words">
                  {source.title}
                </span>
              )}
              {meta && <span className="text-ax-text-secondary text-xs">{meta}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
