"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { useCollator } from "@astryxdesign/core/i18n";
import {
  pixel,
  proportional,
  type TableColumn,
  type TableSortComparator,
  useTableSortable,
  useTableSortableState
} from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookText, History, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useRef, useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { returnTarget } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { rescueFocus } from "@/lib/focus-rescue";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { EntryDialog } from "./entry-dialog";
import {
  type Entry,
  filterEntries,
  PROMPT_LIBRARY_KEY,
  promptLibraryQueryOptions
} from "./prompt-library";
import { VersionHistoryDialog } from "./version-history-dialog";

type SortKey = "name" | "current_version" | "updated_at";

/** Stable while the list is loading, so the filter's memo does not rerun each render. */
const NO_ENTRIES: Entry[] = [];

/** What is open: the create/edit dialog, a prompt's history or a delete confirmation. */
type Flow =
  | { kind: "create" }
  | { kind: "edit"; id: string }
  | { kind: "history"; id: string }
  | { kind: "delete"; id: string }
  | null;

function comparators(
  compare: (a: string, b: string) => number
): Record<SortKey, TableSortComparator<Entry>> {
  return {
    name: (a, b) => compare(a.name, b.name),
    current_version: (a, b) => a.current_version - b.current_version,
    updated_at: (a, b) => Date.parse(a.updated_at) - Date.parse(b.updated_at)
  };
}

/** The row menu: edit, version history, delete. */
function EntryActions({
  entry,
  onEdit,
  onHistory,
  onDelete
}: {
  entry: Entry;
  onEdit: () => void;
  onHistory: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations();
  const name = t("ui_more_actions_for", { name: entry.name });
  return (
    <DropdownMenu
      button={{
        label: name,
        tooltip: name,
        icon: <MoreHorizontal className="size-4" aria-hidden="true" />,
        isIconOnly: true,
        variant: "ghost",
        size: "sm"
      }}
      hasChevron={false}
      alignment="end"
    >
      <DropdownMenuItem icon={Pencil} label={t("edit")} onClick={onEdit} />
      <DropdownMenuItem
        icon={History}
        label={t("prompt_library_show_versions")}
        onClick={onHistory}
      />
      <DropdownMenuDivider />
      <DropdownMenuItem
        icon={Trash2}
        label={t("delete")}
        variant="destructive"
        onClick={onDelete}
      />
    </DropdownMenu>
  );
}

/** The prompts as a sortable table (newest change first) with a row menu. */
function EntryTable({
  entries,
  labelledBy,
  onEdit,
  onHistory,
  onDelete
}: {
  entries: Entry[];
  labelledBy: string;
  onEdit: (entry: Entry) => void;
  onHistory: (entry: Entry) => void;
  onDelete: (entry: Entry) => void;
}) {
  const t = useTranslations();
  const collator = useCollator();
  const compare = useMemo(() => comparators(collator.compare), [collator]);
  const { sortedData, sortConfig } = useTableSortableState<Entry, SortKey>({
    data: entries,
    comparators: compare,
    defaultSort: [{ sortKey: "updated_at", direction: "descending" }]
  });
  const sortPlugin = useTableSortable<Entry, SortKey>(sortConfig);

  const columns: TableColumn<Entry>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(2),
      sortable: true,
      renderCell: (entry) => <span className="font-medium">{entry.name}</span>
    },
    {
      key: "description",
      header: t("description"),
      width: proportional(3),
      renderCell: (entry) => (
        <span className="text-ax-text-secondary">{entry.description ?? "—"}</span>
      )
    },
    {
      key: "current_version",
      header: t("governance_prompts_version"),
      width: pixel(130),
      sortable: true,
      renderCell: (entry) =>
        t("governance_prompt_version_short", { version: String(entry.current_version) })
    },
    {
      key: "updated_at",
      header: t("governance_col_updated"),
      width: proportional(1),
      sortable: true,
      renderCell: (entry) => (
        <span className="text-ax-text-secondary whitespace-nowrap">
          <ClientTime value={entry.updated_at} format="auto" />
        </span>
      )
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (entry) => (
        <EntryActions
          entry={entry}
          onEdit={() => onEdit(entry)}
          onHistory={() => onHistory(entry)}
          onDelete={() => onDelete(entry)}
        />
      )
    }
  ];

  return (
    <div className="border-ax-border bg-ax-card rounded-ax-container [&_thead_tr]:bg-ax-sunken overflow-hidden border">
      {/* Below its min width the table scrolls inside its own named region. */}
      <Table
        data={sortedData}
        columns={columns}
        idKey="id"
        hasHover
        aria-labelledby={labelledBy}
        plugins={{ sort: sortPlugin }}
        className="min-w-160"
      />
    </div>
  );
}

export function PromptLibraryPage() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const list = useQuery(promptLibraryQueryOptions(browserApi));
  const entries = list.data ?? NO_ENTRIES;
  const [search, setSearch] = useState("");
  const [flow, setFlow] = useState<Flow>(null);
  // The control that started the flow (a row's menu button): where focus
  // goes back when the last dialog closes and the dialogs could not return
  // it themselves (edit handed over to the history, whose opener is gone).
  const opener = useRef<HTMLElement | null>(null);

  const filtered = useMemo(() => filterEntries(entries, search), [entries, search]);
  const flowEntry = flow && "id" in flow ? (entries.find((e) => e.id === flow.id) ?? null) : null;

  function start(next: Flow) {
    opener.current = returnTarget();
    setFlow(next);
  }

  function end() {
    setFlow(null);
    rescueFocus(opener.current?.isConnected ? opener.current : headingRef.current);
    opener.current = null;
  }

  const remove = useRemovalMutation({
    mutationFn: (entry: Entry) =>
      unwrap(
        browserApi.DELETE("/api/v1/admin/prompt-library/{id}/", {
          params: { path: { id: entry.id } }
        })
      ),
    refresh: () => queryClient.invalidateQueries({ queryKey: PROMPT_LIBRARY_KEY }),
    onRemoved: (_data, entry) => {
      setFlow(null);
      const message = t("prompt_library_deleted", { name: entry.name });
      announce(message);
      toast.success(message);
    },
    focusTarget: headingRef
    // A prompt the personal assistant's governance uses is refused with its
    // own code (9069); the default error toast says what to do.
  });

  const createButton = (
    <Button
      variant="primary"
      label={t("governance_prompt_create")}
      icon={<Plus aria-hidden="true" />}
      onClick={() => start({ kind: "create" })}
    />
  );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader
        title={t("governance_tab_prompts")}
        description={t("governance_prompts_intro")}
        headingId={headingId}
        headingRef={headingRef}
        actions={createButton}
      />
      <QueryStateBoundary query={list} rows={4}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              icon={<BookText />}
              hue="purple"
              title={t("governance_prompts_empty_title")}
              description={t("governance_prompts_empty_desc")}
              actions={
                <Button
                  variant="primary"
                  label={t("governance_prompts_create_first")}
                  icon={<Plus aria-hidden="true" />}
                  onClick={() => start({ kind: "create" })}
                />
              }
            />
          ) : (
            <div className="flex flex-col gap-4">
              <ResourceFilterInput
                inputRef={searchRef}
                value={search}
                onChange={setSearch}
                label={t("governance_prompts_search_placeholder")}
                placeholder={t("governance_prompts_search_placeholder")}
                resultCount={filtered.length}
              />
              {filtered.length === 0 ? (
                <EmptyState
                  title={t("governance_prompts_no_results")}
                  actions={
                    <Button
                      label={t("clear")}
                      onClick={() => {
                        setSearch("");
                        searchRef.current?.focus();
                      }}
                    />
                  }
                />
              ) : (
                <EntryTable
                  entries={filtered}
                  labelledBy={headingId}
                  onEdit={(entry) => start({ kind: "edit", id: entry.id })}
                  onHistory={(entry) => start({ kind: "history", id: entry.id })}
                  onDelete={(entry) => start({ kind: "delete", id: entry.id })}
                />
              )}
            </div>
          )
        }
      </QueryStateBoundary>
      <EntryDialog
        entry={flow?.kind === "edit" ? flowEntry : null}
        open={flow?.kind === "create" || (flow?.kind === "edit" && flowEntry !== null)}
        onOpenChange={(open) => {
          if (!open) end();
        }}
        onShowHistory={(entry) => setFlow({ kind: "history", id: entry.id })}
      />
      <VersionHistoryDialog
        entry={flow?.kind === "history" ? flowEntry : null}
        open={flow?.kind === "history" && flowEntry !== null}
        onOpenChange={(open) => {
          if (!open) end();
        }}
      />
      <ConfirmDialogControlled
        open={flow?.kind === "delete" && flowEntry !== null}
        onOpenChange={(open) => {
          if (!open) end();
        }}
        title={t("governance_prompts_delete_title")}
        description={t("governance_prompts_delete_named", { name: flowEntry?.name ?? "" })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => {
          if (flowEntry) remove.mutate(flowEntry);
        }}
      />
    </div>
  );
}
