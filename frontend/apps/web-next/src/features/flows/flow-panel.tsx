"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import type { PanelMaximise, PanelSwitcher } from "@/features/chat/side-panel/panel-frame";
import { PanelFrame } from "@/features/chat/side-panel/panel-frame";
import { useSidePanel } from "@/features/chat/side-panel/use-side-panel";
import { useSpace } from "@/features/spaces/use-space";
import { toastApiError } from "@/lib/api/toast";
import { FlowDefinition } from "./flow-definition";
import { FlowHistory } from "./flow-history";
import { isFlowPanelTab } from "./flow-panel-store";
import { FlowRunDetail } from "./flow-run-detail";
import { FlowRunDialog } from "./flow-run-dialog";
import { FlowRunList } from "./flow-run-list";
import { FlowStepEditor } from "./flow-step-editor";
import type { FlowNames } from "./flow-step-summary";
import { FlowStepView } from "./flow-step-view";
import {
  definitionProblems,
  enterEditMode,
  flowKeys,
  flowQueryOptions,
  invalidateFlow,
  leaveEditMode,
  updateFlow
} from "./flows";
import { stepsOf, type FlowDefinition as Definition, type FlowPublic } from "./types";
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

const TAB_PANEL_CLASS =
  "focus-visible:outline-ring min-h-0 flex-1 overflow-y-auto focus-visible:outline-2 focus-visible:-outline-offset-2";

/** The steps the panel changed by hand (saved through it, not the chat). */
function manualChangeCount(flow: FlowPublic): number {
  return (flow.step_origins ?? []).filter((origin) => origin.channel === "api").length;
}

/**
 * The flow page's panel: the flow's definition, its runs and its history on
 * tabs, a "Testkör" button. A flow opens in view mode: a step opens in the
 * read view, maximised over the conversation, and nothing in the panel or
 * the chat changes the flow until the user presses "Redigera". Edit mode
 * is kept on the server per user until "Klar"; in it a step opens in the
 * editor, steps can be added, moved and removed, and the run inputs changed.
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
  const { can } = useSpace();
  const queryClient = useQueryClient();
  const panelId = useId();
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [overviewProblems, setOverviewProblems] = useState<string[]>([]);
  const flowId = store.flowId;
  const flow = useQuery({ ...flowQueryOptions(flowId ?? ""), enabled: flowId !== null });
  const definition = flow.data?.definition ?? null;
  const steps = definition ? stepsOf(definition) : [];
  const stepCount = steps.length;
  const published = flow.data?.published_version != null;
  const canEdit = can("edit", "flow");
  const editing = flow.data?.editing ?? false;

  // The flow's own edit state (per user, kept on the server) drives the mode.
  useEffect(() => {
    store.setMode(editing ? "edit" : "view");
  }, [editing, store]);

  // The step on show, when it is still in the flow (the chat may have removed it).
  const stepKey = store.stepKey;
  const stepGone =
    stepKey !== null && definition !== null && !steps.some((step) => step.key === stepKey);
  useEffect(() => {
    if (stepGone) store.closeStep(panel);
  }, [stepGone, store, panel]);
  // The editor needs edit mode; losing it (another device pressed Klar) ends the edit.
  const editorWithoutMode = store.stepEditing && flow.data !== undefined && !editing;
  useEffect(() => {
    if (editorWithoutMode) store.closeEditor(panel);
  }, [editorWithoutMode, store, panel]);

  const stepOpen = (stepKey !== null && !stepGone) || store.newStep !== null;
  const editorOpen = stepOpen && store.stepEditing && editing;
  const stepScreen = store.tab === "definition" && stepOpen && definition !== null;
  // Maximised and beside the conversation: the step view gets the navigator.
  const wide = panel.maximised && maximise !== null;

  const setFlow = (updated: FlowPublic) => {
    queryClient.setQueryData(flowKeys.flow(updated.id), updated);
    void invalidateFlow(queryClient, updated.id);
  };
  const enter = useMutation({
    mutationFn: (id: string) => enterEditMode(id),
    onSuccess: setFlow,
    onError: (error) => toastApiError(error, t)
  });
  const leave = useMutation({
    mutationFn: (id: string) => leaveEditMode(id),
    onSuccess: setFlow,
    onError: (error) => toastApiError(error, t)
  });
  // Changes made on the overview (moving a step, the run inputs) save the whole definition.
  const saveDefinition = useMutation({
    mutationFn: ({ definition: next, note }: { definition: Definition; note: string }) =>
      updateFlow(flowId!, { definition: next, note }),
    onSuccess: (updated) => {
      setOverviewProblems([]);
      setFlow(updated);
    },
    onError: (error) => {
      const problems = definitionProblems(error);
      if (problems) setOverviewProblems(problems);
      else toastApiError(error, t);
    }
  });

  const openStep = (key: string) => store.openStep(key, panel, { edit: editing });
  const editStep = async (key: string) => {
    if (!editing && flowId) await enter.mutateAsync(flowId);
    store.openStep(key, panel, { edit: true });
  };
  const moveStep = (key: string, direction: -1 | 1) => {
    if (!definition) return;
    const from = steps.findIndex((step) => step.key === key);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= steps.length) return;
    const next = [...steps];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved!);
    saveDefinition.mutate({
      definition: { ...definition, steps: next },
      note: t("flow_editor_move_note", { name: moved!.name, index: to + 1 })
    });
  };

  const manualChanges = flow.data ? manualChangeCount(flow.data) : 0;
  const detail = flow.data
    ? editing
      ? [
          t("flow_mode_editing_draft", { revision: flow.data.revision ?? 1 }),
          manualChanges > 0 ? t("flow_manual_changes", { count: manualChanges }) : null
        ]
          .filter(Boolean)
          .join(" · ")
      : [
          t("flow_steps_count", { count: stepCount }),
          published
            ? t("flow_status_published", { version: flow.data.published_version! })
            : t("flow_status_draft"),
          t("flow_mode_view")
        ].join(" · ")
    : undefined;
  const definitionPanel = `${panelId}-definition`;
  const runsPanel = `${panelId}-runs`;
  const historyPanel = `${panelId}-history`;
  const otherEditors = (flow.data?.editors ?? [])
    .map((editor) => editor.username ?? t("flow_editor_unknown_user"))
    .join(", ");

  const actions = flow.data && !editorOpen && (
    <>
      {!editing && canEdit && (
        <Button
          label={t("flow_edit")}
          size="sm"
          icon={<Pencil className="size-4" />}
          isLoading={enter.isPending}
          isInterruptible
          onClick={() => {
            if (!enter.isPending) enter.mutate(flow.data!.id);
          }}
        />
      )}
      <Button
        label={published && !flow.data.has_unpublished_changes ? t("run") : t("flow_run_test")}
        variant={editing ? "secondary" : "primary"}
        size="sm"
        isDisabled={stepCount === 0}
        onClick={() => setRunDialogOpen(true)}
      />
      {editing && (
        <Button
          label={t("flow_done")}
          variant="primary"
          size="sm"
          icon={<Check className="size-4" />}
          isLoading={leave.isPending}
          isInterruptible
          onClick={() => {
            if (!leave.isPending) leave.mutate(flow.data!.id);
          }}
        />
      )}
    </>
  );

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
      actions={actions || undefined}
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
      ) : stepScreen && editorOpen && flow.data ? (
        <FlowStepEditor
          key={store.newStep ? `new:${store.newStep.kind}:${store.newStep.index}` : stepKey}
          flow={flow.data}
          target={store.newStep ?? { step: steps.find((step) => step.key === stepKey)! }}
          names={names}
          wide={wide}
          onSaved={(key) => store.openStep(key, panel)}
          onCancel={() => store.closeEditor(panel)}
          onOpenRun={(runId) => store.showRun(runId)}
          onDeleted={() => store.closeStep(panel)}
        />
      ) : stepScreen && stepKey !== null ? (
        <FlowStepView
          definition={definition!}
          stepKey={stepKey}
          origins={flow.data?.step_origins ?? []}
          names={names}
          wide={wide}
          onClose={() => store.closeStep(panel)}
          onSelectStep={openStep}
          onEdit={canEdit ? () => void editStep(stepKey) : undefined}
        />
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
          {editing && flow.data && (
            <Banner
              status="info"
              container="section"
              collapsible={false}
              title={t("flow_edit_strip_title")}
              description={[
                t("flow_edit_strip_description", { revision: (flow.data.revision ?? 1) + 1 }),
                otherEditors ? t("flow_edit_strip_others", { names: otherEditors }) : null
              ]
                .filter(Boolean)
                .join(" ")}
            />
          )}
          {store.tab === "definition" ? (
            <div
              id={definitionPanel}
              role="tabpanel"
              tabIndex={0}
              aria-label={t("flow_tab_definition")}
              className={TAB_PANEL_CLASS}
            >
              <QueryStateBoundary query={flow} rows={4}>
                {(data) => (
                  <FlowDefinition
                    flow={data}
                    names={names}
                    canEdit={canEdit}
                    mode={editing ? "edit" : "view"}
                    onOpenStep={openStep}
                    onInsertStep={(kind, index) => store.openNewStep(kind, index, panel)}
                    onMoveStep={moveStep}
                    onSaveInputs={(fields) =>
                      saveDefinition.mutateAsync({
                        definition: { ...data.definition, form_fields: fields },
                        note: t("flow_inputs_note")
                      })
                    }
                    saving={saveDefinition.isPending}
                    problems={overviewProblems}
                  />
                )}
              </QueryStateBoundary>
            </div>
          ) : store.tab === "history" ? (
            <div
              id={historyPanel}
              role="tabpanel"
              tabIndex={0}
              aria-label={t("flow_tab_history")}
              className={TAB_PANEL_CLASS}
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
              className={TAB_PANEL_CLASS}
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
        </>
      )}
      {flow.data && (
        <FlowRunDialog
          flow={flow.data}
          open={runDialogOpen}
          onOpenChange={setRunDialogOpen}
          onStarted={(run) => store.showRun(run.id)}
        />
      )}
    </PanelFrame>
  );
}
