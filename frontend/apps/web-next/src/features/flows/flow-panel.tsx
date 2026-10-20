"use client";

import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQuery } from "@tanstack/react-query";
import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import type { PanelMaximise, PanelSwitcher } from "@/features/chat/side-panel/panel-frame";
import { PanelFrame } from "@/features/chat/side-panel/panel-frame";
import { useSidePanel } from "@/features/chat/side-panel/use-side-panel";
import { useSpace } from "@/features/spaces/use-space";
import { FlowDefinition } from "./flow-definition";
import { FlowHistory } from "./flow-history";
import { isFlowPanelTab } from "./flow-panel-store";
import { FlowRunDetail } from "./flow-run-detail";
import { FlowRunDialog } from "./flow-run-dialog";
import { FlowRunList } from "./flow-run-list";
import type { FlowNames } from "./flow-step-card";
import { flowQueryOptions } from "./flows";
import { stepsOf } from "./types";
import { useFlowPanel } from "./use-flow-panel";

/** Names for the ids in a definition, from the space's models and knowledge. */
function useFlowNames(): FlowNames {
  const { space } = useSpace();
  const byId = <T extends { id: string }>(items: readonly T[] | undefined, id: string) =>
    items?.find((item) => item.id === id) ?? null;
  return {
    modelName: (id) => {
      const model = byId(space.completion_models, id);
      return model ? model.nickname || model.name : null;
    },
    transcriptionModelName: (id) => {
      const model = byId(space.transcription_models, id);
      return model ? model.nickname || model.name : null;
    },
    collectionName: (id) => byId(space.knowledge.groups.items, id)?.name ?? null,
    websiteName: (id) => {
      const website = byId(space.knowledge.websites.items, id);
      return website ? website.name || website.url : null;
    }
  };
}

/**
 * The flow page's panel: the flow's definition on one tab, its runs on the
 * other, a "Kör" button for a published flow. Read-only; the chat is where
 * a flow changes, and the panel refetches when a flows tool call finishes.
 */
export function FlowPanel({
  switcher,
  maximise
}: {
  switcher: PanelSwitcher | null;
  maximise: PanelMaximise | null;
}) {
  const t = useTranslations();
  const panel = useSidePanel()!;
  const store = useFlowPanel()!;
  const names = useFlowNames();
  const panelId = useId();
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const flowId = store.flowId;
  const flow = useQuery({ ...flowQueryOptions(flowId ?? ""), enabled: flowId !== null });
  const definition = flow.data?.definition ?? null;
  const stepCount = definition ? stepsOf(definition).length : 0;
  const published = flow.data?.published_version != null;
  const detail = flow.data
    ? [
        t("flow_steps_count", { count: stepCount }),
        published
          ? t("flow_status_published", { version: flow.data.published_version! })
          : t("flow_status_draft")
      ].join(" · ")
    : undefined;
  const definitionPanel = `${panelId}-definition`;
  const runsPanel = `${panelId}-runs`;
  const historyPanel = `${panelId}-history`;

  return (
    <PanelFrame
      icon={<Workflow className="size-4" />}
      tileClassName="bg-ax-purple-muted text-ax-purple"
      title={flow.data?.name ?? t("flow_new_title")}
      detail={detail}
      switcher={switcher}
      maximise={maximise}
      onClose={() => panel.closeNative()}
      closeLabel={t("flow_panel_close")}
      actions={
        flow.data ? (
          <Button
            label={t("run")}
            variant="primary"
            size="sm"
            isDisabled={!published}
            onClick={() => setRunDialogOpen(true)}
          />
        ) : undefined
      }
    >
      {flowId === null ? (
        <div className="flex min-h-0 flex-1 flex-col p-4">
          <EmptyState
            isCompact
            headingLevel={3}
            icon={<Workflow />}
            hue="purple"
            title={t("flow_panel_empty_title")}
            description={t("flow_panel_empty_description")}
          />
        </div>
      ) : (
        <>
          <div className="border-ax-border shrink-0 border-b px-4 py-1.5">
            <TabList
              role="tablist"
              value={store.tab}
              onChange={(value) => store.setTab(isFlowPanelTab(value) ? value : "definition")}
              size="sm"
              aria-label={t("flow_panel_tabs_label")}
            >
              <Tab value="definition" label={t("flow_tab_definition")} panelId={definitionPanel} />
              <Tab value="runs" label={t("flow_tab_runs")} panelId={runsPanel} />
              <Tab value="history" label={t("flow_tab_history")} panelId={historyPanel} />
            </TabList>
          </div>
          {store.tab === "definition" ? (
            <div
              id={definitionPanel}
              role="tabpanel"
              tabIndex={0}
              aria-label={t("flow_tab_definition")}
              className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto focus-visible:outline-2 focus-visible:-outline-offset-2"
            >
              <QueryStateBoundary query={flow} rows={4}>
                {(data) => <FlowDefinition flow={data} names={names} />}
              </QueryStateBoundary>
            </div>
          ) : store.tab === "history" ? (
            <div
              id={historyPanel}
              role="tabpanel"
              tabIndex={0}
              aria-label={t("flow_tab_history")}
              className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto focus-visible:outline-2 focus-visible:-outline-offset-2"
            >
              <QueryStateBoundary query={flow} rows={4}>
                {(data) => (
                  <FlowHistory
                    flow={data}
                    names={names}
                    onRestored={() => store.setTab("definition")}
                  />
                )}
              </QueryStateBoundary>
            </div>
          ) : (
            <div
              id={runsPanel}
              role="tabpanel"
              tabIndex={0}
              aria-label={t("flow_tab_runs")}
              className="focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto focus-visible:outline-2 focus-visible:-outline-offset-2"
            >
              {store.runId ? (
                <FlowRunDetail
                  flowId={flowId}
                  runId={store.runId}
                  definition={definition}
                  onBack={() => store.selectRun(null)}
                />
              ) : (
                <div className="p-2">
                  <FlowRunList
                    flowId={flowId}
                    selectedRunId={null}
                    onSelect={(runId) => store.selectRun(runId)}
                  />
                </div>
              )}
            </div>
          )}
          {flow.data && (
            <FlowRunDialog
              flow={flow.data}
              open={runDialogOpen}
              onOpenChange={setRunDialogOpen}
              onStarted={(run) => store.showRun(run.id)}
            />
          )}
        </>
      )}
    </PanelFrame>
  );
}
