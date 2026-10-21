"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Token } from "@astryxdesign/core/Token";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { FlowDefinition } from "./flow-definition";
import type { FlowNames } from "./flow-step-summary";
import {
  flowRevisionQueryOptions,
  flowRevisionsQueryOptions,
  invalidateFlow,
  restoreFlowRevision
} from "./flows";
import type {
  FlowPublic,
  FlowRevisionChangesPublic,
  FlowRevisionPublic,
  FlowRevisionSummaryPublic
} from "./types";

type Translate = ReturnType<typeof useTranslations>;

const ROW_CLASS =
  "focus-visible:outline-ring hover:bg-ax-hover flex min-h-11 w-full items-start gap-2.5 rounded-ax-inner px-2 py-2 text-start text-[13px] focus-visible:outline-2 focus-visible:-outline-offset-2";

/** "Steg tillagt: X · Namn ändrat": what a revision changed, in one line. */
export function changesSummary(changes: FlowRevisionChangesPublic, t: Translate): string {
  if (changes.is_initial) return t("flow_history_initial");
  const parts: string[] = [];
  if (changes.name_changed) parts.push(t("flow_history_name_changed"));
  if (changes.description_changed) parts.push(t("flow_history_description_changed"));
  if (changes.form_fields_changed) parts.push(t("flow_history_inputs_changed"));
  const steps = (key: string, names: string[] | undefined) => {
    if (names?.length) parts.push(t(key, { count: names.length, names: names.join(", ") }));
  };
  steps("flow_history_steps_added", changes.steps_added);
  steps("flow_history_steps_removed", changes.steps_removed);
  steps("flow_history_steps_changed", changes.steps_changed);
  return parts.length > 0 ? parts.join(" · ") : t("flow_history_no_changes");
}

/** Where a revision came from: the flows chat, the API, or an API key. */
function sourceLabel(revision: Pick<FlowRevisionSummaryPublic, "channel" | "principal_type">) {
  if (revision.principal_type === "service") return "flow_history_via_service";
  return revision.channel === "mcp" ? "flow_history_via_chat" : "flow_history_via_api";
}

/** The revision as the definition component reads a flow. */
function revisionAsFlow(flow: FlowPublic, revision: FlowRevisionPublic): FlowPublic {
  return {
    id: flow.id,
    space_id: flow.space_id,
    name: revision.name,
    description: revision.description,
    definition: revision.definition,
    published_version: revision.published_version,
    has_unpublished_changes: false,
    revision: revision.revision,
    conversation_id: flow.conversation_id,
    created_at: revision.created_at,
    updated_at: revision.created_at
  };
}

function RevisionMeta({ revision }: { revision: FlowRevisionSummaryPublic }) {
  const t = useTranslations();
  return (
    <span className="text-ax-text-secondary text-xs">
      <ClientTime value={revision.created_at} format="auto" />
      {" · "}
      {t(sourceLabel(revision))}
    </span>
  );
}

function RevisionList({
  flow,
  onSelect
}: {
  flow: FlowPublic;
  onSelect: (revision: number) => void;
}) {
  const t = useTranslations();
  const revisions = useInfiniteQuery(flowRevisionsQueryOptions(flow.id));
  const items = revisions.data?.pages.flatMap((page) => page.items) ?? [];
  const current = flow.revision ?? items[0]?.revision ?? null;

  return (
    <QueryStateBoundary query={revisions} rows={3}>
      {() =>
        items.length === 0 ? (
          <EmptyState
            isCompact
            framed={false}
            headingLevel={3}
            title={t("flow_history_empty_title")}
            description={t("flow_history_empty_description")}
          />
        ) : (
          <div className="flex flex-col gap-2">
            <ul
              aria-label={t("flow_history_list_label")}
              className="m-0 flex list-none flex-col p-0"
            >
              {items.map((revision) => (
                <li key={revision.revision}>
                  <button
                    type="button"
                    aria-label={t("flow_history_open", { revision: revision.revision })}
                    onClick={() => onSelect(revision.revision)}
                    className={ROW_CLASS}
                  >
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="font-medium">
                          {t("flow_history_revision", { revision: revision.revision })}
                        </span>
                        {revision.revision === current && (
                          <Token size="sm" color="blue" label={t("flow_history_current")} />
                        )}
                        {revision.published_version != null && (
                          <Badge
                            variant="success"
                            label={t("flow_status_published", {
                              version: revision.published_version
                            })}
                          />
                        )}
                      </span>
                      <RevisionMeta revision={revision} />
                      {revision.note && (
                        <span className="text-ax-text text-[13px] leading-snug">
                          {revision.note}
                        </span>
                      )}
                      <span className="text-ax-text-secondary text-xs leading-snug">
                        {changesSummary(revision.changes, t)}
                      </span>
                    </span>
                    <ChevronRight
                      aria-hidden="true"
                      className="text-ax-text-tertiary mt-0.5 size-4 shrink-0"
                    />
                  </button>
                </li>
              ))}
            </ul>
            {revisions.hasNextPage && (
              <Button
                label={revisions.isFetchingNextPage ? t("loading") : t("load_more")}
                size="sm"
                className="self-center"
                isLoading={revisions.isFetchingNextPage}
                isInterruptible
                onClick={() => {
                  if (!revisions.isFetchingNextPage) void revisions.fetchNextPage();
                }}
              />
            )}
            {revisions.isFetchNextPageError && (
              <ListError error={revisions.error} onRetry={() => void revisions.fetchNextPage()} />
            )}
          </div>
        )
      }
    </QueryStateBoundary>
  );
}

function RevisionDetail({
  flow,
  revision,
  names,
  onBack,
  onRestored
}: {
  flow: FlowPublic;
  revision: number;
  names: FlowNames;
  onBack: () => void;
  onRestored: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const detail = useQuery(flowRevisionQueryOptions(flow.id, revision));
  const [confirming, setConfirming] = useState(false);
  const isCurrent = flow.revision === revision;
  const restore = useMutation({
    mutationFn: () => restoreFlowRevision(flow.id, revision, flow.revision ?? 1),
    onSuccess: () => {
      void invalidateFlow(queryClient, flow.id);
      setConfirming(false);
      toast.success(t("flow_history_restored", { revision }));
      onRestored();
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="flex flex-col gap-4 p-4">
      <Button label={t("flow_history_back")} variant="ghost" size="sm" onClick={onBack} />
      <QueryStateBoundary query={detail} rows={4}>
        {(data) => (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="flex min-w-0 flex-col gap-1">
                <h3 className="m-0 text-sm font-semibold">
                  {t("flow_history_revision", { revision: data.revision })}
                </h3>
                <RevisionMeta revision={data} />
                {data.note && (
                  <p className="text-ax-text m-0 text-[13px] leading-snug">{data.note}</p>
                )}
                <span className="text-ax-text-secondary text-xs leading-snug">
                  {changesSummary(data.changes, t)}
                </span>
              </div>
              {isCurrent ? (
                <Token size="sm" color="blue" label={t("flow_history_current")} />
              ) : (
                <Button
                  label={t("flow_history_restore")}
                  variant="primary"
                  size="sm"
                  onClick={() => setConfirming(true)}
                />
              )}
            </div>
            {isCurrent && (
              <p className="text-ax-text-secondary m-0 text-[13px]">
                {t("flow_history_is_current")}
              </p>
            )}
            <div className="border-ax-border rounded-ax-container -mx-4 border-t">
              <FlowDefinition flow={revisionAsFlow(flow, data)} names={names} />
            </div>
          </div>
        )}
      </QueryStateBoundary>
      <ConfirmDialogControlled
        open={confirming}
        onOpenChange={setConfirming}
        title={t("flow_history_restore_title", { revision })}
        description={t("flow_history_restore_description", { revision })}
        confirmLabel={t("flow_history_restore")}
        variant="default"
        pending={restore.isPending}
        onConfirm={() => restore.mutate()}
      />
    </div>
  );
}

/**
 * The flow's history: every save as a revision, newest first, with who
 * made it, the note given with it and what it changed. A row opens the
 * revision's definition read-only; an older revision can be restored,
 * which saves it as a new revision and returns to the definition tab.
 */
export function FlowHistory({
  flow,
  names = {},
  onRestored
}: {
  flow: FlowPublic;
  names?: FlowNames;
  /** Called after a restore succeeded (the panel shows the definition again). */
  onRestored: () => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  if (selected !== null) {
    return (
      <RevisionDetail
        flow={flow}
        revision={selected}
        names={names}
        onBack={() => setSelected(null)}
        onRestored={() => {
          setSelected(null);
          onRestored();
        }}
      />
    );
  }
  return (
    <div className="p-2">
      <RevisionList flow={flow} onSelect={setSelected} />
    </div>
  );
}
