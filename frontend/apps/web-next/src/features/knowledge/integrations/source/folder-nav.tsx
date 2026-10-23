"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import {
  ChevronRight,
  CircleCheck,
  CircleDashed,
  CircleMinus,
  CircleX,
  Clock,
  LoaderCircle,
  Search,
  type LucideIcon
} from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { TextInput } from "@astryxdesign/core/TextInput";
import { cn } from "@/lib/utils";
import type { IntegrationKnowledge } from "../../knowledge";
import {
  buildIntegrationTree,
  filterIntegrationTree,
  flattenIntegrationTree
} from "../integration-tree";
import { itemState, sourceStateStatus, type ItemState, type QueuedIds } from "../sources";
import type { ProgressById } from "../sync-progress";
import type { InPlaceLink } from "./in-place-link";

/** Below this many folders the whole tree fits and a filter only adds noise. */
const FILTER_FROM = 8;

// A shape per state, so the state never rests on colour alone; the label is for screen readers.
const STATE_ICON: Record<ItemState, { icon: LucideIcon; className: string }> = {
  ok: { icon: CircleCheck, className: "text-ax-success" },
  error: { icon: CircleX, className: "text-ax-error" },
  syncing: { icon: LoaderCircle, className: "text-ax-text-accent motion-safe:animate-spin" },
  queued: { icon: Clock, className: "text-ax-text-accent" },
  empty: { icon: CircleMinus, className: "text-ax-warning" },
  never: { icon: CircleDashed, className: "text-ax-text-secondary" }
};

const LINK =
  "focus-visible:outline-ring rounded-ax-inner flex min-h-9 min-w-0 flex-1 items-center gap-2.5 pe-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11";

function StateIcon({ state }: { state: ItemState }) {
  const { icon: Icon, className } = STATE_ICON[state];
  return <Icon className={cn("size-3.5 shrink-0", className)} aria-hidden="true" />;
}

/**
 * The folders of a source as a tree of links: "All folders" first, then each
 * folder with its state and documents. Parents collapse; a filter appears
 * once the tree is long, and opens every match while it is in use.
 */
export function FolderNav({
  items,
  progress,
  queued,
  selectedId,
  linkFor
}: {
  items: IntegrationKnowledge[];
  progress: ProgressById;
  queued: QueuedIds;
  /** Null selects the overview of every folder. */
  selectedId: string | null;
  linkFor: (itemId: string | null) => InPlaceLink;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const collator = useCollator();
  const headingId = useId();
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());

  const filtering = query.trim() !== "";
  const rows = flattenIntegrationTree(
    filterIntegrationTree(buildIntegrationTree(items, collator.compare), query),
    (item) => filtering || !collapsed.has(item.id)
  );
  const totalDocuments = items.reduce((sum, item) => sum + (item.metadata?.document_count ?? 0), 0);

  function countLabel(item: IntegrationKnowledge, state: ItemState): string {
    const entry = progress[item.id];
    if (entry) {
      return entry.total === null
        ? format.number(entry.done)
        : `${format.number(entry.done)}/${format.number(entry.total)}`;
    }
    if (state === "never") return "–";
    return format.number(item.metadata?.document_count ?? 0);
  }

  function toggle(itemId: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  return (
    <nav aria-labelledby={headingId} className="flex flex-col gap-1">
      <h2
        id={headingId}
        className="text-ax-text-secondary px-2 pb-1 text-xs font-medium tracking-wide uppercase"
      >
        {t("integration_source_folders")}
      </h2>
      {items.length > FILTER_FROM ? (
        <div className="mb-1">
          <TextInput
            label={t("integration_source_filter_folders")}
            isLabelHidden
            placeholder={t("integration_source_filter_folders")}
            value={query}
            onChange={setQuery}
            startIcon={Search}
            hasClear
            size="sm"
            width="100%"
          />
        </div>
      ) : null}
      <ul className="flex flex-col gap-0.5">
        {!filtering ? (
          <li>
            <Link
              {...linkFor(null)}
              prefetch={false}
              aria-current={selectedId === null ? "page" : undefined}
              className={cn(
                LINK,
                "ps-9",
                selectedId === null ? "bg-ax-selected font-medium" : "hover:bg-ax-hover"
              )}
            >
              <span className="flex-1 truncate">{t("integration_source_all_folders")}</span>
              <span className="text-ax-text-secondary text-xs tabular-nums">
                {format.number(totalDocuments)}
              </span>
            </Link>
          </li>
        ) : null}
        {rows.map((row) => {
          const state = itemState(row.item, progress, queued);
          const selected = selectedId === row.item.id;
          return (
            <li
              key={row.item.id}
              className="flex items-center"
              style={{ paddingInlineStart: `${row.depth * 1.25}rem` }}
            >
              {row.hasChildren && !filtering ? (
                <button
                  type="button"
                  aria-expanded={row.expanded}
                  aria-label={t(
                    row.expanded
                      ? "integration_source_collapse_folder"
                      : "integration_source_expand_folder",
                    { name: row.item.name }
                  )}
                  onClick={() => toggle(row.item.id)}
                  className="text-ax-text-secondary hover:bg-ax-hover focus-visible:outline-ring rounded-ax-inner flex size-7 shrink-0 items-center justify-center focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:size-11"
                >
                  <ChevronRight
                    className={cn("size-4 transition-transform", row.expanded && "rotate-90")}
                    aria-hidden="true"
                  />
                </button>
              ) : (
                <span className="w-7 shrink-0 pointer-coarse:w-11" aria-hidden="true" />
              )}
              <Link
                {...linkFor(row.item.id)}
                prefetch={false}
                aria-current={selected ? "page" : undefined}
                title={row.item.folder_path ?? row.item.name}
                className={cn(
                  LINK,
                  "ps-1",
                  selected ? "bg-ax-selected font-medium" : "hover:bg-ax-hover"
                )}
              >
                <StateIcon state={state} />
                <span className="flex-1 truncate">{row.item.name}</span>
                <span className="sr-only">, {t(sourceStateStatus(state).labelKey)}</span>
                <span
                  className={cn(
                    "text-xs tabular-nums",
                    state === "syncing" ? "text-ax-text-accent" : "text-ax-text-secondary"
                  )}
                >
                  {countLabel(row.item, state)}
                </span>
              </Link>
            </li>
          );
        })}
        {rows.length === 0 ? (
          <li className="text-ax-text-secondary px-2 py-2 text-sm">{t("no_results_found")}</li>
        ) : null}
      </ul>
      <p className="text-ax-text-secondary px-2 pt-2 text-xs leading-relaxed">
        {t("integration_source_subfolders_included")}
      </p>
    </nav>
  );
}
