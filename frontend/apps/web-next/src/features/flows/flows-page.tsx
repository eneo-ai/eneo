"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, SearchX, Trash2, Upload, Workflow } from "lucide-react";
import Link from "@/lib/link";
import { replaceUrl, usePathname, useSearchParams } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { useAnnounceChange } from "@/lib/hooks/use-announce-change";
import { HANDHELD_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { useSearchDraft } from "@/lib/hooks/use-search-draft";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { useSpace } from "@/features/spaces/use-space";
import { deleteFlow, flowKeys, flowsListQueryOptions, type FlowSparse } from "./flows-api";
import { evidenceExportAllowed } from "./flow-form-fields";
import { FLOW_LIST_STATUSES, visibleFlows, type FlowListStatus } from "./flow-list-filter";
import { FlowPackageImportDialog } from "./flow-package-import-dialog";
import { flowRefusalMessage } from "./flow-refusals";
import { flowListHref, parseFlowListSearch } from "./flow-search";
import { FlowRows, flowKindLine } from "./flows-rows";
import { FlowStatusBadge } from "./flow-status";
import { NewFlowDialog } from "./new-flow-dialog";

/**
 * A space's flows, the last changed first: name and description, what each
 * takes in and gives back, whether it is published, how many steps it has,
 * whose it is and when it last changed. A search and (for those who manage
 * flows) a state filter narrow the list; both live in the address. "Nytt
 * flöde" creates an empty draft and opens it; a flow is built on its own page,
 * by hand or in its chat. A flow's own controls follow what the core says the
 * caller may do with it.
 */
export function FlowsPage() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { can } = useAppContext();
  const queryClient = useQueryClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const allStatesRef = useRef<HTMLButtonElement>(null);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<FlowSparse | null>(null);
  const flows = useQuery(flowsListQueryOptions(browserApi, space.id));
  const canManage = can("flows_manage");
  // A phone runs and reviews flows; building one (many settings, prompts and
  // steps) is for a computer, so nothing here offers to.
  const phone = useMediaMatch(HANDHELD_QUERY);
  const base = `/spaces/${routeId}/flows`;

  const pathname = usePathname();
  const searchParams = useSearchParams();
  const view = parseFlowListSearch({
    q: searchParams.get("q"),
    status: searchParams.get("status")
  });
  // The list follows each key; the address follows once typing pauses.
  const { draft, setDraft, settled } = useSearchDraft(view.q ?? "");
  // Others see published flows only, so only those who manage flows filter by state.
  const status: FlowListStatus = canManage ? (view.status ?? "all") : "all";
  const kindLine = (flow: FlowSparse) => flowKindLine(flow, t);
  const shown = visibleFlows(flows.data ?? [], { query: draft, status }, kindLine);
  const count = t("flow_list_count", { count: shown.length });
  // The search field announces its own matches; a change of state is said here.
  useAnnounceChange(count, status);

  useEffect(() => {
    if (settled !== (view.q ?? "")) {
      replaceUrl(flowListHref(pathname, searchParams, { q: settled }));
    }
  }, [settled, view.q, pathname, searchParams]);

  function showState(next: FlowListStatus) {
    replaceUrl(flowListHref(pathname, searchParams, { status: next }));
  }

  const remove = useRemovalMutation({
    mutationFn: (flow: FlowSparse) => deleteFlow(flow.id),
    refresh: () => queryClient.invalidateQueries({ queryKey: flowKeys.list(space.id) }),
    onRemoved: (_data, flow) => {
      setDeleteTarget(null);
      toast.success(t("flows_deleted", { name: flow.name }));
    },
    // A refusal (one the flags did not foresee, such as a 403) says why in words.
    onError: (error) => toast.error(flowRefusalMessage(error, [], t)),
    focusTarget: headingRef
  });

  const createButton =
    canManage && !phone ? (
      <div className="flex flex-wrap items-center gap-2">
        <Button
          label={t("flow_editor_tools_package_import")}
          icon={<Upload aria-hidden="true" />}
          onClick={() => setImporting(true)}
        />
        <Button
          label={t("flows_new")}
          variant="primary"
          icon={<Plus aria-hidden="true" />}
          onClick={() => setCreating(true)}
        />
      </div>
    ) : undefined;

  const columns: TableColumn<FlowSparse>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(3),
      renderCell: (flow) => (
        <span className="flex min-w-0 flex-col gap-0.5 py-1">
          <Link
            href={`${base}/${flow.id}`}
            className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 w-fit items-center font-semibold break-words hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
          >
            {flow.name}
          </Link>
          {flow.description ? (
            <span className="text-ax-text-secondary text-xs break-words">{flow.description}</span>
          ) : null}
        </span>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: pixel(170),
      renderCell: (flow) => <FlowStatusBadge publishedVersion={flow.published_version} />
    },
    {
      key: "steps",
      header: t("flows_steps_heading"),
      width: pixel(110),
      renderCell: (flow) => t("flows_step_count", { count: flow.step_count })
    },
    {
      key: "updated",
      header: t("flows_updated"),
      width: pixel(170),
      // The date the list sorts by: a flow never changed since it was created shows when that was.
      renderCell: (flow) => {
        const changed = flow.updated_at ?? flow.created_at;
        return changed ? <ClientTime value={changed} format="auto" /> : "—";
      }
    },
    ...((flows.data ?? []).some((flow) => flow.permissions.can_delete)
      ? [
          {
            key: "actions",
            header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
            width: pixel(72),
            align: "end" as const,
            renderCell: (flow: FlowSparse) =>
              flow.permissions.can_delete ? (
                <IconButton
                  label={t("flows_delete_named", { name: flow.name })}
                  icon={<Trash2 aria-hidden="true" />}
                  variant="ghost"
                  size="sm"
                  onClick={() => setDeleteTarget(flow)}
                />
              ) : null
          }
        ]
      : [])
  ];

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        headingLevel={2}
        headingRef={headingRef}
        title={t("flows")}
        description={t("flows_list_description")}
        actions={createButton}
      />
      <QueryStateBoundary query={flows} rows={3}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              icon={<Workflow />}
              hue="purple"
              headingLevel={3}
              title={t("flows_empty_title")}
              description={t("flows_empty_description")}
              actions={createButton}
            />
          ) : (
            // One set of controls above both layouts, so a search being typed
            // and the chosen state survive a turn across the breakpoint.
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center">
                <ResourceFilterInput
                  value={draft}
                  onChange={setDraft}
                  label={t("flow_list_search_aria")}
                  placeholder={t("flow_list_search_placeholder")}
                  resultCount={shown.length}
                  inputRef={searchRef}
                  className="md:w-80"
                />
                {canManage ? (
                  <SegmentedControl
                    label={t("flow_list_filter_aria")}
                    value={status}
                    onChange={(next) => showState(next as FlowListStatus)}
                  >
                    {FLOW_LIST_STATUSES.map((option) => (
                      <SegmentedControlItem
                        key={option}
                        ref={option === "all" ? allStatesRef : undefined}
                        value={option}
                        label={t(`flow_list_filter_${option}`)}
                      />
                    ))}
                  </SegmentedControl>
                ) : null}
                <p className="text-ax-text-secondary text-sm md:ms-auto">{count}</p>
              </div>
              {shown.length === 0 ? (
                draft.trim() ? (
                  <EmptyState
                    icon={<SearchX />}
                    headingLevel={3}
                    isCompact
                    title={t("flow_list_no_match_title")}
                    actions={
                      <Button
                        label={t("flow_list_clear_search")}
                        onClick={() => {
                          setDraft("");
                          searchRef.current?.focus();
                        }}
                      />
                    }
                  />
                ) : (
                  <EmptyState
                    icon={<SearchX />}
                    headingLevel={3}
                    isCompact
                    title={
                      status === "published"
                        ? t("flow_list_no_published_title")
                        : t("flow_list_no_drafts_title")
                    }
                    actions={
                      <Button
                        label={t("flow_list_show_all")}
                        onClick={() => {
                          showState("all");
                          allStatesRef.current?.focus();
                        }}
                      />
                    }
                  />
                )
              ) : phone ? (
                <FlowRows flows={shown} base={base} showStatus={canManage} />
              ) : (
                <Table
                  data={shown}
                  columns={columns}
                  idKey="id"
                  aria-label={t("flows")}
                  pinnedColumn="name"
                />
              )}
            </div>
          )
        }
      </QueryStateBoundary>
      {phone && canManage ? (
        <p className="text-ax-text-secondary -mt-2 text-sm">{t("flows_create_on_desktop")}</p>
      ) : null}
      <NewFlowDialog open={creating} onOpenChange={setCreating} />
      {canManage ? <FlowPackageImportDialog open={importing} onOpenChange={setImporting} /> : null}
      <AlertDialog
        isOpen={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !remove.isPending) setDeleteTarget(null);
        }}
        title={t("flows_delete_title", { name: deleteTarget?.name ?? "" })}
        description={
          // A deleted flow can no longer be changed, so its runs' evidence
          // could then never be downloaded: say so before it is too late.
          deleteTarget && !evidenceExportAllowed(deleteTarget.metadata_json)
            ? `${t("flows_delete_description")} ${t("flow_delete_evidence_export_off")}`
            : t("flows_delete_description")
        }
        actionLabel={t("delete")}
        cancelLabel={t("cancel")}
        isActionLoading={remove.isPending}
        onAction={() => {
          if (deleteTarget && !remove.isPending) remove.mutate(deleteTarget);
        }}
      />
    </div>
  );
}
