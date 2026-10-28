"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { Pagination } from "@astryxdesign/core/Pagination";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import {
  pixel,
  proportional,
  useTableSortable,
  type TableColumn,
  type TableSortState
} from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useQuery } from "@tanstack/react-query";
import { Check, ExternalLink, FileText, Search } from "lucide-react";
import Link from "@/lib/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime, useClientTimeText } from "@/components/composites/client-time";
import { ListError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { MEDIA } from "@/lib/breakpoints";
import { formatBytes } from "@/lib/format";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useSpace } from "@/features/spaces/use-space";
import type { IntegrationKnowledge } from "../../knowledge";
import { BlobPreviewDialog } from "../../blobs";
import { IntegrationActions } from "../actions";
import { safeExternalUrl } from "../external-url";
import {
  DOCUMENTS_PAGE_SIZE,
  integrationDocumentsQueryOptions,
  type IntegrationDocument,
  type IntegrationDocumentsSort
} from "../queries";
import { describeSkipReason } from "../skip-reasons";
import type { SkippedDocuments } from "../source-problems";
import { SourceStateLabel, useWatchStates } from "../source-status";
import { itemState, watchStateLabel, type QueuedIds } from "../sources";
import type { ProgressById } from "../sync-progress";
import { VENDOR } from "../vendor";
import type { InPlaceLink } from "./in-place-link";
import { LiveSyncFeed } from "./live-sync-feed";

/** Below Tailwind's `sm`, page numbers at 44 px touch sizes overflow a phone. */
const NARROW_QUERY = `not all and ${MEDIA.sm}`;

type DocumentsView = "searchable" | "skipped";
type DocumentRow = IntegrationDocument;

const DEFAULT_SORT: TableSortState<IntegrationDocumentsSort> = [
  { sortKey: "path", direction: "ascending" }
];

/** The document name opens its text and its source properties. */
function DocumentNameCell({ document }: { document: IntegrationDocument }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-ax-text focus-visible:outline-ring rounded-ax-inner flex min-h-6 max-w-full items-center gap-2.5 text-start font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
      >
        <span
          aria-hidden="true"
          className="bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-7 shrink-0 items-center justify-center"
        >
          <FileText className="size-4" />
        </span>
        <span className="break-words">{document.title}</span>
      </button>
      {open ? (
        <BlobPreviewDialog
          blob={{ id: document.id, metadata: { title: document.title } }}
          properties={document.source_metadata ?? []}
          open={open}
          onOpenChange={setOpen}
        />
      ) : null}
    </>
  );
}

function FolderHeader({
  item,
  progress,
  queued,
  showControls
}: {
  item: IntegrationKnowledge;
  progress: ProgressById;
  queued: QueuedIds;
  showControls: boolean;
}) {
  const t = useTranslations();
  const synced = useClientTimeText(item.metadata?.last_synced_at, "date_time");
  const attempted = useClientTimeText(item.metadata?.last_sync_attempted_at, "date_time");
  const [watch] = useWatchStates([item]) ?? [];
  const url = safeExternalUrl(item.url);
  const state = itemState(item, progress, queued);
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h2
          id={`folder-documents-${item.id}`}
          tabIndex={-1}
          className="focus-visible:outline-ring rounded-ax-inner text-base font-semibold break-words focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {item.name}
          {item.original_name && item.original_name !== item.name ? (
            <span className="text-ax-text-secondary ms-1 text-sm font-normal">
              ({item.original_name})
            </span>
          ) : null}
        </h2>
        <div className="text-ax-text-secondary flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <SourceStateLabel state={state} className="text-xs" />
          {item.metadata?.last_synced_at ? (
            synced ? (
              <span>{t("integration_source_last_up_to_date_at", { time: synced })}</span>
            ) : null
          ) : attempted ? (
            <span>{t("integration_source_last_attempt_at", { time: attempted })}</span>
          ) : null}
          {item.integration_type === "sharepoint" && watch ? (
            <span className={watch === "expired" ? "text-ax-warning" : undefined}>
              {t("integration_source_watch_state_line", { state: watchStateLabel(watch, t) })}
            </span>
          ) : null}
          {item.folder_path ? <span className="break-all">{item.folder_path}</span> : null}
        </div>
      </div>
      {showControls ? (
        <div className="flex items-center gap-1">
          {url ? (
            <Button
              label={t(VENDOR[item.integration_type].linkLabel)}
              size="sm"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              icon={<ExternalLink className="size-4" aria-hidden="true" />}
            />
          ) : null}
          <IntegrationActions item={item} syncActive={state === "syncing" || state === "queued"} />
        </div>
      ) : null}
    </div>
  );
}

function SkippedFiles({
  item,
  skipped,
  problemsLink
}: {
  item: IntegrationKnowledge;
  skipped: SkippedDocuments;
  problemsLink: InPlaceLink;
}) {
  const t = useTranslations();
  if (skipped.items.length === 0) {
    return (
      <p className="text-ax-text-secondary py-8 text-sm">
        {t("integration_source_nothing_skipped")}
      </p>
    );
  }
  const notListed = Math.max(0, skipped.total - skipped.items.length);
  const rows = skipped.items.map((file, index) => ({ id: `${index}:${file.file}`, ...file }));
  const columns: TableColumn<(typeof rows)[number]>[] = [
    {
      key: "file",
      header: t("name"),
      width: proportional(2),
      renderCell: (row) => <span className="font-semibold break-all">{row.file}</span>
    },
    {
      key: "reason",
      header: t("integration_source_skip_reason"),
      width: proportional(3),
      renderCell: (row) => <span className="text-ax-warning">{describeSkipReason(row, t)}</span>
    }
  ];
  return (
    <>
      <Table
        data={rows}
        columns={columns}
        idKey="id"
        aria-label={t("integration_source_skipped_table_label", { name: item.name })}
      />
      <p className="text-ax-text-secondary flex flex-wrap gap-x-3 text-sm">
        {notListed > 0 ? (
          <span className="italic">{t("skipped_and_n_more", { count: notListed })}</span>
        ) : null}
        <Link
          {...problemsLink}
          prefetch={false}
          className="text-ax-text-accent focus-visible:outline-ring rounded-ax-inner font-medium hover:underline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t("integration_source_show_in_problems")}
        </Link>
      </p>
    </>
  );
}

/**
 * One synced folder (or file, page): what is searchable, page by page with a
 * search over names, paths and properties, and what its latest sync could not
 * read. While it syncs, the files being read show above.
 */
export function FolderDocuments({
  item,
  progress,
  queued,
  skipped,
  problemsLink,
  showHeader = true,
  showControls = true
}: {
  item: IntegrationKnowledge;
  progress: ProgressById;
  queued: QueuedIds;
  /** The files the latest sync skipped; null while unknown or not loadable. */
  skipped: SkippedDocuments | null;
  problemsLink: InPlaceLink;
  /** The folder's own heading; off when the source is this one item. */
  showHeader?: boolean;
  /** The folder's link and actions in its heading; off when the page header has them. */
  showControls?: boolean;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const isNarrow = useMediaQuery(NARROW_QUERY);
  const { space } = useSpace();
  const sectionRef = useRef<HTMLElement>(null);
  const rescue = useFocusRescue();
  const [view, setView] = useState<DocumentsView>("searchable");
  const [searchInput, setSearchInput] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState(DEFAULT_SORT);
  const [page, setPage] = useState(1);

  // A new search starts over at page 1.
  const debouncedQ = useDebouncedValue(searchInput.trim());
  if (debouncedQ !== q) {
    setQ(debouncedQ);
    setPage(1);
  }

  const [active] = sort;
  const documents = useQuery(
    integrationDocumentsQueryOptions(browserApi, {
      spaceId: space.id,
      item,
      q,
      sort: active?.sortKey ?? "path",
      order: active?.direction === "descending" ? "desc" : "asc",
      page
    })
  );
  const sortPlugin = useTableSortable<DocumentRow, IntegrationDocumentsSort>({
    sort,
    onSortChange: (next) => {
      setSort(next.length > 0 ? next : DEFAULT_SORT);
      setPage(1);
    },
    allowUnsortedState: false
  });

  const data = documents.data;
  const state = itemState(item, progress, queued);
  const live = progress[item.id];
  const lastPage = data ? Math.max(1, Math.ceil(data.total_count / DOCUMENTS_PAGE_SIZE)) : 1;
  // A sync that shrank the folder under the current page: show its last page.
  if (data && !documents.isPlaceholderData && page > lastPage) setPage(lastPage);
  // An empty page of a folder that has documents: one past the end, on its way to the last page.
  const pastTheEnd =
    data !== undefined &&
    data.items.length === 0 &&
    data.total_count > 0 &&
    (documents.isPlaceholderData || page > lastPage);

  function changePage(next: number) {
    setPage(next);
    // The pressed button stays focused, except "next"/"previous" at the last
    // or first page, which becomes disabled: then focus moves to the folder.
    rescue(sectionRef.current);
  }

  const emptyText =
    q !== ""
      ? t("no_results_found")
      : state === "syncing" || state === "queued"
        ? t("integration_source_folder_empty_syncing")
        : state === "never"
          ? t("integration_documents_empty_never_synced")
          : t("integration_documents_empty_synced");
  const rangeText =
    data && data.items.length > 0
      ? t("integration_documents_showing_range", {
          from: data.offset + 1,
          to: data.offset + data.items.length,
          total: data.total_count
        })
      : null;
  // What a search or sort the reader started led to, once it is in. Astryx's
  // Pagination announces a page turn itself; the first load and a reload after
  // a sync are not results.
  const resultText = rangeText ?? (q !== "" ? emptyText : null);
  const settled = data !== undefined && !documents.isFetching && !pastTheEnd;
  const asked = `${q}|${active?.sortKey ?? ""}|${active?.direction ?? ""}`;
  const announcedView = useRef(asked);
  useEffect(() => {
    if (!settled || announcedView.current === asked) return;
    announcedView.current = asked;
    if (resultText !== null) announce(resultText);
  }, [announce, asked, resultText, settled]);

  const columns: TableColumn<DocumentRow>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(2),
      sortable: true,
      renderCell: (row) => <DocumentNameCell document={row} />
    },
    {
      key: "path",
      header: t("integration_documents_path"),
      width: proportional(1),
      sortable: true,
      renderCell: (row) => (
        <span className="text-ax-text-secondary block truncate" title={row.relative_path}>
          {row.relative_path}
        </span>
      )
    },
    {
      key: "size",
      header: t("size"),
      width: pixel(100),
      sortable: true,
      renderCell: (row) => <span className="tabular-nums">{formatBytes(row.size, locale)}</span>
    },
    {
      key: "updated_at",
      header: t("integration_documents_updated"),
      width: proportional(1),
      sortable: true,
      renderCell: (row) =>
        row.updated_at ? <ClientTime value={row.updated_at} format="date_time" /> : "–"
    },
    {
      key: "status",
      header: t("status"),
      width: pixel(120),
      renderCell: () => (
        <span className="text-ax-success inline-flex items-center gap-1.5 text-sm">
          <Check className="size-4" aria-hidden="true" />
          {t("integration_source_doc_searchable")}
        </span>
      )
    },
    {
      key: "link",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (row) => {
        const url = safeExternalUrl(row.url);
        return url ? (
          <Button
            variant="ghost"
            size="sm"
            isIconOnly
            label={t("integration_source_open_item_link", {
              label: t(VENDOR[item.integration_type].linkLabel),
              name: row.title
            })}
            icon={<ExternalLink className="size-4" aria-hidden="true" />}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
          />
        ) : null;
      }
    }
  ];

  return (
    <section
      ref={sectionRef}
      // Takes focus when the pressed page button disables at the first or last page.
      tabIndex={-1}
      className="focus-visible:outline-ring rounded-ax-element flex min-w-0 flex-col gap-3 focus-visible:outline-2 focus-visible:outline-offset-4"
      aria-labelledby={`folder-documents-${item.id}`}
    >
      {showHeader ? (
        <FolderHeader item={item} progress={progress} queued={queued} showControls={showControls} />
      ) : (
        <h2 id={`folder-documents-${item.id}`} tabIndex={-1} className="sr-only">
          {t("documents")}
        </h2>
      )}

      {live ? <LiveSyncFeed progress={live} /> : null}

      <SegmentedControl
        label={t("integration_source_document_views")}
        value={view}
        onChange={(value) => setView(value === "skipped" && skipped ? "skipped" : "searchable")}
        size="sm"
      >
        <SegmentedControlItem
          value="searchable"
          label={t("integration_source_view_searchable", {
            count: item.metadata?.document_count ?? 0
          })}
        />
        <SegmentedControlItem
          value="skipped"
          label={t("integration_source_view_unreadable", { count: skipped?.total ?? 0 })}
          isDisabled={skipped === null}
        />
      </SegmentedControl>

      {view === "skipped" && skipped ? (
        <SkippedFiles item={item} skipped={skipped} problemsLink={problemsLink} />
      ) : (
        <>
          <div className="max-w-md">
            <TextInput
              label={t("integration_documents_search_label")}
              isLabelHidden
              placeholder={t("integration_documents_search_placeholder")}
              value={searchInput}
              onChange={setSearchInput}
              startIcon={Search}
              hasClear
              width="100%"
            />
          </div>

          {documents.isPending || pastTheEnd ? (
            <LoadingState label={t("integration_documents_loading")} rows={5} />
          ) : documents.isError ? (
            <ListError
              error={documents.error}
              title={t("integration_documents_load_failed")}
              isRetrying={documents.isFetching}
              onRetry={() => void documents.refetch()}
            />
          ) : data && data.items.length > 0 ? (
            <>
              <div aria-busy={documents.isFetching || undefined}>
                <Table
                  data={data.items}
                  columns={columns}
                  idKey="id"
                  aria-label={t("integration_documents_table_label", { name: item.name })}
                  plugins={{ sort: sortPlugin }}
                />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <p className="text-ax-text-secondary">
                  {rangeText} ·{" "}
                  {t("integration_documents_total_size", {
                    size: formatBytes(data.total_size, locale)
                  })}
                </p>
                {/* Never disabled while a page loads: that would take focus from the
                    pressed button. The previous page stays visible (aria-busy). */}
                {lastPage > 1 ? (
                  <Pagination
                    page={Math.min(page, lastPage)}
                    totalPages={lastPage}
                    onChange={changePage}
                    variant={isNarrow ? "compact" : "pages"}
                    size="sm"
                    label={t("integration_documents_pagination_label", { name: item.name })}
                  />
                ) : null}
              </div>
            </>
          ) : (
            <p className="text-ax-text-secondary py-8 text-sm">{emptyText}</p>
          )}
        </>
      )}
    </section>
  );
}
