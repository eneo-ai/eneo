"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { Token } from "@astryxdesign/core/Token";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Workflow } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { getErrorMessage } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import { createFlow } from "./flow-create";
import { runStatusLabel, runStatusTone, stepKindLabel } from "./flow-labels";
import { FlowRunDialog } from "./flow-run-dialog";
import { NewFlowDialog } from "./new-flow-dialog";
import { deleteFlow, flowQueryOptions, flowsListQueryOptions } from "./flows";
import type { FlowSparsePublic } from "./types";

/** "Kör" from the list: loads the flow's definition (the form fields) and opens the run dialog. */
function RunFromList({
  flowId,
  routeId,
  onClose
}: {
  flowId: string;
  routeId: string;
  onClose: () => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const flow = useQuery(flowQueryOptions(flowId));
  if (!flow.data) {
    // The definition is a short load; a failure is said in the dialog's place.
    return (
      <Dialog isOpen={flow.isError} onOpenChange={(open) => !open && onClose()} width={480}>
        <Layout
          height="auto"
          header={<DialogHeader title={t("run")} onOpenChange={(open) => !open && onClose()} />}
          content={
            <LayoutContent>
              <ListError error={flow.error} onRetry={() => void flow.refetch()} />
            </LayoutContent>
          }
        />
      </Dialog>
    );
  }
  return (
    <FlowRunDialog
      flow={flow.data}
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      onStarted={(run) => router.push(`/spaces/${routeId}/flows/${flowId}?run=${run.id}`)}
    />
  );
}

/**
 * The flows of a space: name, the kinds of its steps, whether it is
 * published, its latest run, and the ways in (its runs, a new run, delete).
 * "Nytt flöde" opens a fresh authoring chat.
 */
export function FlowsPage() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const queryClient = useQueryClient();
  const router = useRouter();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<FlowSparsePublic | null>(null);
  const [runTarget, setRunTarget] = useState<string | null>(null);
  const base = `/spaces/${routeId}/flows`;
  const flows = useQuery(flowsListQueryOptions(space.id));

  const remove = useRemovalMutation({
    mutationFn: (flow: FlowSparsePublic) => deleteFlow(flow.id),
    refresh: () =>
      queryClient.invalidateQueries({ queryKey: flowsListQueryOptions(space.id).queryKey }),
    onRemoved: (_data, flow) => {
      toast.success(t("flow_deleted", { name: flow.name }));
      setDeleteTarget(null);
    },
    onError: (error) => toast.error(getErrorMessage(error, t)),
    focusTarget: headingRef
  });

  const columns: TableColumn<FlowSparsePublic>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(3),
      renderCell: (flow) => (
        <span className="flex min-w-0 flex-col">
          <Link
            className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 items-center font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
            href={`${base}/${flow.id}`}
          >
            {flow.name}
          </Link>
          {flow.description && (
            <span className="text-ax-text-secondary line-clamp-2 text-xs">{flow.description}</span>
          )}
        </span>
      )
    },
    {
      key: "steps",
      header: t("flow_section_steps"),
      width: proportional(2),
      renderCell: (flow) => (
        <span className="flex flex-wrap gap-1">
          {flow.step_kinds.map((kind, index) => (
            <Token key={`${kind}-${index}`} size="sm" label={stepKindLabel(kind, t)} />
          ))}
        </span>
      )
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      renderCell: (flow) => (
        <Badge
          variant={flow.published_version != null ? "success" : "neutral"}
          label={
            flow.published_version != null
              ? t("flow_status_published", { version: flow.published_version })
              : t("flow_status_draft")
          }
        />
      )
    },
    {
      key: "last_run",
      header: t("flow_last_run"),
      width: proportional(2),
      renderCell: (flow) =>
        flow.last_run ? (
          <span className="flex min-w-0 flex-col gap-0.5">
            <StatusLabel
              status={runStatusTone(flow.last_run.status)}
              label={runStatusLabel(flow.last_run.status, t)}
              isPulsing={flow.last_run.status === "running"}
            />
            <span className="text-ax-text-secondary text-xs">
              <ClientTime value={flow.last_run.created_at} format="auto" />
            </span>
          </span>
        ) : (
          <span className="text-ax-text-secondary">{t("flow_never_run")}</span>
        )
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(can("delete", "flow") ? 260 : 200),
      align: "end" as const,
      renderCell: (flow) => (
        <span className="flex items-center justify-end gap-1">
          <Button
            label={t("flow_tab_runs")}
            size="sm"
            variant="ghost"
            href={`${base}/${flow.id}?tab=runs`}
          />
          <Button
            label={flow.published_version != null ? t("run") : t("flow_run_test")}
            size="sm"
            isDisabled={flow.step_count === 0}
            onClick={() => setRunTarget(flow.id)}
          />
          {can("delete", "flow") && (
            <IconButton
              label={t("flow_delete_aria", { name: flow.name })}
              icon={<Trash2 aria-hidden="true" />}
              variant="ghost"
              size="sm"
              onClick={() => setDeleteTarget(flow)}
            />
          )}
        </span>
      )
    }
  ];

  // "Nytt flöde" creates the draft first and opens its chat: the assistant
  // then only edits this flow, it never creates one.
  const [newFlowOpen, setNewFlowOpen] = useState(false);
  const create = useMutation({
    mutationFn: (name: string) => createFlow(space.id, name),
    onSuccess: (flow) => {
      void queryClient.invalidateQueries({ queryKey: flowsListQueryOptions(space.id).queryKey });
      router.push(`${base}/${flow.id}`);
    },
    onError: (error) => toast.error(getErrorMessage(error, t))
  });
  const createButton = can("create", "flow") ? (
    <Button
      label={t("flow_new")}
      variant="primary"
      icon={<Plus aria-hidden="true" />}
      onClick={() => setNewFlowOpen(true)}
    />
  ) : undefined;

  return (
    <div className="flex w-full flex-col gap-6 pb-16">
      <PageHeader
        headingLevel={2}
        headingRef={headingRef}
        title={t("flows")}
        description={t("flows_intro")}
        actions={createButton}
      />
      <QueryStateBoundary query={flows} rows={3}>
        {(page) =>
          page.items.length === 0 ? (
            <EmptyState
              icon={<Workflow />}
              hue="purple"
              headingLevel={3}
              title={t("flows_empty_title")}
              description={t("flows_empty_description")}
              actions={createButton}
            />
          ) : (
            <SpaceTableFrame>
              <Table data={page.items} columns={columns} idKey="id" aria-label={t("flows")} />
            </SpaceTableFrame>
          )
        }
      </QueryStateBoundary>
      <NewFlowDialog
        open={newFlowOpen}
        pending={create.isPending}
        onCancel={() => setNewFlowOpen(false)}
        onCreate={(name) => create.mutate(name)}
      />
      <ConfirmDialogControlled
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={t("flow_delete_title")}
        description={t("flow_delete_description", { name: deleteTarget?.name ?? "" })}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget)}
      />
      {runTarget && (
        <RunFromList flowId={runTarget} routeId={routeId} onClose={() => setRunTarget(null)} />
      )}
    </div>
  );
}
