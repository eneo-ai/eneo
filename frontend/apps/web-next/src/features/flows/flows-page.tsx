"use client";

import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Workflow } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import { deleteFlow, flowKeys, flowsListQueryOptions, type FlowSparse } from "./flows-api";
import { FlowStatusBadge } from "./flow-status";
import { NewFlowDialog } from "./new-flow-dialog";

/**
 * A space's flows: name and description, whether each is published, how many
 * steps it has and when it last changed. "Nytt flöde" creates an empty draft
 * and opens it; a flow is built on its own page, by hand or in its chat.
 */
export function FlowsPage() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { can } = useAppContext();
  const queryClient = useQueryClient();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<FlowSparse | null>(null);
  const flows = useQuery(flowsListQueryOptions(browserApi, space.id));
  const canManage = can("flows_manage");
  const base = `/spaces/${routeId}/flows`;

  const remove = useRemovalMutation({
    mutationFn: (flow: FlowSparse) => deleteFlow(flow.id),
    refresh: () => queryClient.invalidateQueries({ queryKey: flowKeys.list(space.id) }),
    onRemoved: (_data, flow) => {
      setDeleteTarget(null);
      toast.success(t("flows_deleted", { name: flow.name }));
    },
    focusTarget: headingRef
  });

  const createButton = canManage ? (
    <Button
      label={t("flows_new")}
      variant="primary"
      icon={<Plus aria-hidden="true" />}
      onClick={() => setCreating(true)}
    />
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
      renderCell: (flow) =>
        flow.updated_at ? <ClientTime value={flow.updated_at} format="auto" /> : "—"
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
            width: pixel(72),
            align: "end" as const,
            renderCell: (flow: FlowSparse) => (
              <IconButton
                label={t("flows_delete_named", { name: flow.name })}
                icon={<Trash2 aria-hidden="true" />}
                variant="ghost"
                size="sm"
                onClick={() => setDeleteTarget(flow)}
              />
            )
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
            <SpaceTableFrame>
              <Table
                data={items}
                columns={columns}
                idKey="id"
                aria-label={t("flows")}
                className="min-w-[640px]"
              />
            </SpaceTableFrame>
          )
        }
      </QueryStateBoundary>
      <NewFlowDialog open={creating} onOpenChange={setCreating} />
      <ConfirmDialogControlled
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !remove.isPending) setDeleteTarget(null);
        }}
        title={t("flows_delete_title", { name: deleteTarget?.name ?? "" })}
        description={t("flows_delete_description")}
        confirmLabel={t("delete")}
        variant="destructive"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleteTarget) remove.mutate(deleteTarget);
        }}
      />
    </div>
  );
}
