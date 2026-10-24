"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { focusAfterRemoval } from "@/lib/focus-after-removal";
import { useFocusRescue } from "@/lib/focus-rescue";
import { cn } from "@/lib/utils";
import { useSpaceDisplayName, useSpaceSections } from "@/features/spaces/frame/space-header";
import { spaceLandingHref } from "@/features/spaces/frame/space-sections";
import { useSpace } from "@/features/spaces/use-space";
import { AddStepDialog } from "./editor/add-step-dialog";
import { flowEditorKeys, insertionKindsQueryOptions } from "./editor/editor-api";
import { FlowStepEditor } from "./editor/flow-step-editor";
import type { StepKindOption } from "./editor/step-kinds";
import {
  flowKeys,
  flowQueryOptions,
  publishFlow,
  refusalCode,
  storeFlow,
  unpublishFlow,
  updateFlowEditor,
  type FlowDefinitionUpdate,
  type FlowEditorUpdate,
  type FlowPublic,
  type FlowStep
} from "./flows-api";
import { describeChanges, diffFlowSteps, hasChanges, type StepChange } from "./flow-changes";
import { FlowChatPanel } from "./flow-chat-panel";
import { FlowDraftCheck } from "./flow-draft-check-panel";
import { FlowPackageExportDialog } from "./flow-package-export-dialog";
import { stepLabel } from "./flow-labels";
import { flowRefusalMessage, STALE_REVISION } from "./flow-refusals";
import { FlowSettings } from "./flow-settings";
import { FlowStatusBadge } from "./flow-status";
import { FlowStepList, stepControlId } from "./flow-step-list";
import { orderWithMove, orderWithout, stepsInOrder } from "./flow-steps";
import { speakerStepCandidate, speakerStepOption, speakerStepUpdate } from "./speaker-step-offer";
import { runKeys } from "./runs/runs-api";
import { FlowRunsList, runHref } from "./runs/runs-list";
import { rememberStartedRun } from "./runs/runs-optimistic";
import { StartRunDialog } from "./runs/start-run-dialog";

type Notice = { key: number; status: "error" | "warning"; title: string; description: string };
type View = "definition" | "chat";
type PageTab = "definition" | "runs";
type EditorChange = Omit<FlowEditorUpdate, "expected_revision" | "definition"> & {
  definition?: FlowDefinitionUpdate;
};

const CHAT_WIDTH_STORAGE_KEY = "eneo:flow-chat-width";
/** How long a card the chat touched stays marked. */
const CHAT_CHANGE_MARK_MS = 8000;

/** After a move the moved step's button keeps focus; at an end, where it is disabled, its twin. */
function focusMoveControl(stepId: string, delta: -1 | 1) {
  requestAnimationFrame(() => {
    const same = document.getElementById(stepControlId(stepId, delta < 0 ? "up" : "down"));
    const other = document.getElementById(stepControlId(stepId, delta < 0 ? "down" : "up"));
    const target = same instanceof HTMLButtonElement && !same.disabled ? same : other;
    target?.focus();
  });
}

/**
 * A flow's page: its definition (settings and steps, each with what it reads
 * and produces) beside its chat. Changes go through the core's editor as one
 * revision-fenced edit each; a refusal is shown above both columns with how
 * to fix it, and a stale draft is reloaded. Publishing freezes the
 * definition until it is unpublished. On a phone the two columns are one
 * view at a time.
 */
export function FlowPage({ flowId }: { flowId: string }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const rescue = useFocusRescue();
  const { routeId, space } = useSpace();
  const spaceName = useSpaceDisplayName();
  const sections = useSpaceSections();
  const { data: flow } = useSuspenseQuery(flowQueryOptions(browserApi, flowId));
  const steps = stepsInOrder(flow);
  const isPublished = flow.published_version != null;
  // What the caller may do with this flow, as the core reports it; a flag is
  // permission, not state (a published flow still reports `can_edit`).
  const { permissions } = flow;
  const mayEdit = permissions.can_edit;
  const canEdit = mayEdit && !isPublished;
  const canPublish = permissions.can_publish;
  // Unpublishing leads to editing only for someone who may do both.
  const canUnpublishToEdit = canPublish && mayEdit;
  const canRun = isPublished && permissions.can_run;
  const canViewRuns = permissions.can_view_runs;

  const stepsHeadingRef = useRef<HTMLHeadingElement>(null);
  const editorRef = useRef<HTMLElement>(null);
  const noticeKey = useRef(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [view, setView] = useState<View>("definition");
  // From lg the chat sits beside the definition with a handle between them;
  // below that the tabs toggle the two. The row is the basis of the chat's
  // share only while it is beside: a phone-wide row would clamp the
  // remembered width down and lose it.
  const beside = useMediaQuery("(min-width: 1024px)");
  const row = useRef<HTMLDivElement>(null);
  const chat = useResizable({
    containerRef: row,
    defaultSize: "44%",
    minSize: 352,
    maxSize: "60%",
    autoSaveId: CHAT_WIDTH_STORAGE_KEY
  });
  const [openStepId, setOpenStepId] = useState<string | null>(null);
  const [addAt, setAddAt] = useState<number | null>(null);
  const [confirmUnpublish, setConfirmUnpublish] = useState(false);
  const [starting, setStarting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const [chosenTab, setTab] = useState<PageTab>(
    searchParams.get("tab") === "runs" ? "runs" : "definition"
  );
  const tab: PageTab = canViewRuns ? chosenTab : "definition";
  const tabsId = useId();
  const tabId = (id: PageTab) => `${tabsId}-tab-${id}`;
  const panelId = `${tabsId}-panel`;

  /** The tab lives in ?tab=, so a run's page can link back to the list. */
  function selectTab(next: PageTab) {
    setTab(next);
    const url = new URL(window.location.href);
    if (next === "runs") url.searchParams.set("tab", "runs");
    else url.searchParams.delete("tab");
    window.history.replaceState(null, "", url);
  }

  /** A refusal above both columns; a stale draft is reloaded first. */
  const refused = useCallback(
    (error: unknown, title: string, against: readonly FlowStep[]) => {
      const stale = refusalCode(error) === STALE_REVISION;
      if (stale) void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flowId) });
      noticeKey.current += 1;
      setNotice({
        key: noticeKey.current,
        status: stale ? "warning" : "error",
        title: stale ? t("flows_notice_stale_title") : title,
        description: flowRefusalMessage(error, against, t)
      });
    },
    [flowId, queryClient, t]
  );

  const saved = (updated: FlowPublic) => {
    storeFlow(queryClient, updated);
    setNotice(null);
  };

  const edit = useMutation({
    mutationFn: (change: EditorChange) =>
      updateFlowEditor(flowId, {
        ...change,
        definition: change.definition ?? {},
        expected_revision: flow.draft_revision
      }),
    onSuccess: saved,
    onError: (error) => refused(error, t("flows_notice_not_saved"), steps)
  });

  const publish = useMutation({
    mutationFn: () => publishFlow(flow),
    onSuccess: (updated) => {
      saved(updated);
      announce(t("flows_published", { version: updated.published_version ?? "" }));
    },
    onError: (error) => refused(error, t("flows_notice_not_published"), steps)
  });

  const unpublish = useMutation({
    mutationFn: () => unpublishFlow(flow),
    onSuccess: (updated) => {
      saved(updated);
      setConfirmUnpublish(false);
      announce(t("flows_unpublished"));
    },
    onError: (error) => {
      setConfirmUnpublish(false);
      refused(error, t("flows_notice_not_unpublished"), steps);
    }
  });

  // A new draft revision can carry rewritten prompts (a chat tool's edit, a
  // move whose reads the core followed, a reload of a stale draft): the step
  // assistants are read again then, and only then.
  const assistantsRevision = useRef(flow.draft_revision);
  useEffect(() => {
    if (assistantsRevision.current === flow.draft_revision) return;
    assistantsRevision.current = flow.draft_revision;
    void queryClient.invalidateQueries({ queryKey: flowEditorKeys.assistants(flowId) });
  }, [flow.draft_revision, flowId, queryClient]);

  /** After the chat's tools ran or it answered: reread the flow and say when it changed. */
  // The cards the chat's tools touched last, marked for a while.
  const [chatChanges, setChatChanges] = useState<ReadonlyMap<string, StepChange> | null>(null);
  useEffect(() => {
    if (!chatChanges) return;
    const timer = window.setTimeout(() => setChatChanges(null), CHAT_CHANGE_MARK_MS);
    return () => window.clearTimeout(timer);
  }, [chatChanges]);

  const refreshFromChat = useCallback(async () => {
    const before = queryClient.getQueryData<FlowPublic>(flowKeys.flow(flowId));
    try {
      const after = await unwrap(
        browserApi.GET("/api/v1/flows/{id}/", { params: { path: { id: flowId } } })
      );
      const changed =
        before !== undefined &&
        (after.draft_revision !== before.draft_revision ||
          after.published_version !== before.published_version);
      const changes = before ? diffFlowSteps(before, after) : null;
      const apply = () =>
        flushSync(() => {
          queryClient.setQueryData(flowKeys.flow(flowId), after);
          setChatChanges(changes && hasChanges(changes) ? changes.steps : null);
        });
      // The cards move, appear and leave with a view transition where the
      // browser has one and the person has not asked for less motion.
      if (
        changes &&
        hasChanges(changes) &&
        typeof document.startViewTransition === "function" &&
        !window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ) {
        document.startViewTransition(apply);
      } else {
        apply();
      }
      if (changed) {
        void queryClient.invalidateQueries({ queryKey: flowKeys.list(after.space_id) });
        announce((changes && describeChanges(changes, after, t)) ?? t("flows_chat_changed_flow"));
      }
    } catch {
      // The next action reads the flow again; a failed reread is not news.
    }
  }, [announce, flowId, queryClient, t]);

  function requestPublish() {
    if (publish.isPending) return;
    if (steps.length === 0) {
      noticeKey.current += 1;
      setNotice({
        key: noticeKey.current,
        status: "error",
        title: t("flows_notice_not_published"),
        description: t("flows_publish_needs_steps")
      });
      return;
    }
    publish.mutate();
  }

  function openStep(step: FlowStep) {
    if (!step.id) return;
    // Rendered before focus moves, so the editor is there to take it.
    flushSync(() => setOpenStepId(step.id ?? null));
    editorRef.current?.focus();
  }

  function closeStep() {
    const id = openStepId;
    setOpenStepId(null);
    if (id)
      requestAnimationFrame(() => document.getElementById(stepControlId(id, "open"))?.focus());
  }

  function moveStep(step: FlowStep, delta: -1 | 1) {
    if (edit.isPending || !step.id) return;
    const order = orderWithMove(steps, step.id, delta);
    if (!order) return;
    const id = step.id;
    edit.mutate(
      { step_order: order },
      {
        onSuccess: () => {
          announce(
            t("flows_step_moved", { step: stepLabel(step, t), position: step.step_order + delta })
          );
          focusMoveControl(id, delta);
        }
      }
    );
  }

  async function removeStep(step: FlowStep) {
    if (!step.id) return;
    const next = focusAfterRemoval(document.getElementById(stepControlId(step.id, "open")));
    try {
      await edit.mutateAsync({ step_order: orderWithout(steps, step.id) });
      announce(t("flows_step_removed", { step: stepLabel(step, t) }));
      rescue(() => next() ?? stepsHeadingRef.current);
    } catch {
      // Refused: the notice above the columns says why.
    }
  }

  /** Adds the step that names the speakers after `after`; focus goes to the new step. */
  function addSpeakerStep(after: FlowStep, option: StepKindOption) {
    if (edit.isPending) return;
    const update = speakerStepUpdate(flow, after, option, {
      step: t("flows_speaker_step_name"),
      fieldLabel: t("flows_speaker_participants_label"),
      fieldName: t("flows_speaker_participants_name")
    });
    edit.mutate(update, {
      onSuccess: (updated) => {
        announce(t("flows_step_added"));
        const added = stepsInOrder(updated).find(
          (step) => step.step_order === after.step_order + 1
        );
        rescue(
          () =>
            (added?.id ? document.getElementById(stepControlId(added.id, "open")) : null) ??
            stepsHeadingRef.current
        );
      }
    });
  }

  /** Saves a step's underlag with a read of a removed step replaced (the draft check's repair). */
  async function repairReference(
    step: FlowStep,
    inputBindings: Record<string, unknown> | null
  ): Promise<boolean> {
    if (!step.id || edit.isPending) return false;
    try {
      await edit.mutateAsync({
        step_edits: [{ step_id: step.id, changes: { input_bindings: inputBindings } }]
      });
      announce(t("flow_editor_tools_repair_done", { step: stepLabel(step, t) }));
      return true;
    } catch {
      // Refused: the notice above the columns says why.
      return false;
    }
  }

  async function saveSettings(definition: FlowDefinitionUpdate): Promise<boolean> {
    try {
      await edit.mutateAsync({ definition });
      announce(t("flows_settings_saved"));
      return true;
    } catch {
      return false;
    }
  }

  const openedStep = openStepId ? steps.find((step) => step.id === openStepId) : undefined;
  const speakerCandidate = canEdit
    ? speakerStepCandidate(flow, space.transcription_services ?? [])
    : null;
  // The core decides whether the speaker step may follow the candidate.
  const speakerKinds = useQuery({
    ...insertionKindsQueryOptions(
      flow.id,
      flow.draft_revision,
      (speakerCandidate?.step_order ?? 0) + 1
    ),
    enabled: speakerCandidate !== null
  });
  const speakerOption = speakerCandidate ? speakerStepOption(speakerKinds.data) : null;

  const actions =
    mayEdit || canPublish || canRun ? (
      <div className="flex flex-wrap items-center gap-2">
        {canRun ? (
          <Button
            label={t("flow_runs_start")}
            variant="primary"
            onClick={() => setStarting(true)}
          />
        ) : null}
        {mayEdit ? (
          <Button
            label={t("flow_editor_tools_package_export")}
            onClick={() => setExporting(true)}
          />
        ) : null}
        {canPublish && isPublished ? (
          <Button
            label={t("unpublish")}
            onClick={() => setConfirmUnpublish(true)}
            isLoading={unpublish.isPending}
            isInterruptible
          />
        ) : null}
        {canPublish && !isPublished ? (
          <Button
            label={t("publish")}
            variant="primary"
            onClick={requestPublish}
            isLoading={publish.isPending}
            isInterruptible
          />
        ) : null}
      </div>
    ) : undefined;

  return (
    <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">
      <div className="border-ax-border flex flex-col gap-3 border-b px-6 pt-4 pb-3">
        <PageHeader
          title={flow.name}
          description={flow.description?.trim() || undefined}
          breadcrumbs={[
            { label: spaceName, href: spaceLandingHref(sections, routeId) },
            { label: t("flows"), href: `/spaces/${routeId}/flows` },
            { label: flow.name, current: true }
          ]}
          actions={
            <>
              <FlowStatusBadge publishedVersion={flow.published_version} />
              {actions}
            </>
          }
        />
        {notice ? (
          <Banner
            role={notice.status === "error" || notice.status === "warning" ? "alert" : "status"}
            key={notice.key}
            status={notice.status}
            title={notice.title}
            description={notice.description}
            isDismissable
            dismissLabel={t("flows_notice_dismiss")}
            onDismiss={() => setNotice(null)}
          />
        ) : null}
        <div className="lg:hidden">
          <SegmentedControl
            label={t("flows_view_label")}
            value={view}
            onChange={(next) => setView(next as View)}
            layout="fill"
          >
            <SegmentedControlItem value="definition" label={t("flows_view_definition")} />
            <SegmentedControlItem value="chat" label={t("flows_view_chat")} />
          </SegmentedControl>
        </div>
      </div>

      <div
        ref={beside ? row : null}
        className="flex min-w-0 flex-col lg:min-h-0 lg:flex-1 lg:flex-row"
      >
        <section
          aria-label={t("flows_view_definition")}
          className={cn(
            "flex min-w-0 flex-col gap-6 px-6 py-5 lg:min-h-0 lg:flex-1 lg:overflow-y-auto",
            view !== "definition" && "max-lg:hidden"
          )}
        >
          {canViewRuns ? (
            <TabList
              role="tablist"
              aria-label={t("flow_runs_tabs_label")}
              value={tab}
              onChange={(value) => selectTab(value as PageTab)}
              hasDivider
            >
              <Tab
                id={tabId("definition")}
                value="definition"
                label={t("flow_runs_tab_definition")}
                panelId={panelId}
              />
              <Tab
                id={tabId("runs")}
                value="runs"
                label={t("flow_runs_tab_runs")}
                panelId={panelId}
              />
            </TabList>
          ) : null}
          <div
            role={canViewRuns ? "tabpanel" : undefined}
            id={panelId}
            aria-labelledby={canViewRuns ? tabId(tab) : undefined}
            className="flex min-w-0 flex-col gap-6"
          >
            {tab === "runs" ? (
              <FlowRunsList
                flowId={flow.id}
                spaceRouteId={routeId}
                publishedVersion={flow.published_version ?? null}
              />
            ) : openedStep?.id ? (
              <section
                ref={editorRef}
                tabIndex={-1}
                aria-label={t("flows_step_editor_region", { step: stepLabel(openedStep, t) })}
                className="focus-visible:outline-ring rounded-ax-inner focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <FlowStepEditor
                  flow={flow}
                  stepId={openedStep.id}
                  readOnly={!canEdit}
                  onSaved={(updated) => {
                    saved(updated);
                    announce(t("flows_step_saved", { step: stepLabel(openedStep, t) }));
                  }}
                  onCancel={closeStep}
                />
              </section>
            ) : (
              <>
                {isPublished ? (
                  <Banner
                    status="info"
                    title={t("flows_published_title", { version: flow.published_version ?? "" })}
                    description={
                      canUnpublishToEdit
                        ? t("flows_published_description")
                        : t("flows_published_read_only")
                    }
                    collapsible={false}
                    endContent={
                      canUnpublishToEdit ? (
                        <Button
                          label={t("flows_unpublish_to_edit")}
                          size="sm"
                          onClick={() => setConfirmUnpublish(true)}
                        />
                      ) : undefined
                    }
                  />
                ) : null}
                {canEdit ? (
                  <FlowDraftCheck
                    flow={flow}
                    speakerServices={space.transcription_services ?? []}
                    onOpenStep={openStep}
                    onRepair={repairReference}
                  />
                ) : null}
                <FlowStepList
                  flowId={flow.id}
                  steps={steps}
                  canEdit={canEdit}
                  mayEdit={mayEdit}
                  changes={chatChanges}
                  headingRef={stepsHeadingRef}
                  onOpen={openStep}
                  onMove={moveStep}
                  onRemove={removeStep}
                  onAdd={(position) => setAddAt(position)}
                  speakerOffer={
                    speakerCandidate?.id && speakerOption
                      ? {
                          stepId: speakerCandidate.id,
                          pending: edit.isPending,
                          onAccept: () => addSpeakerStep(speakerCandidate, speakerOption)
                        }
                      : null
                  }
                />
                <FlowSettings
                  flow={flow}
                  canEdit={canEdit}
                  transcription={{
                    models: space.transcription_models,
                    services: space.transcription_services ?? []
                  }}
                  onSave={saveSettings}
                />
              </>
            )}
          </div>
        </section>

        {beside && (
          // The chat sits at the end of the row: dragging the handle left widens it.
          <ResizeHandle
            isReversed
            hasDivider
            label={t("flows_chat_resize_handle")}
            resizable={chat.props}
          />
        )}
        <section
          aria-label={t("flows_chat_heading")}
          style={beside ? { width: chat.size } : undefined}
          className={cn(
            "border-ax-border flex h-[85dvh] min-h-[28rem] min-w-0 flex-col border-t lg:h-auto lg:min-h-0 lg:shrink-0 lg:border-t-0",
            view !== "chat" && "max-lg:hidden"
          )}
        >
          <FlowChatPanel
            flow={flow}
            onFlowMayHaveChanged={() => void refreshFromChat()}
            onRefused={(error, title) => refused(error, title, steps)}
          />
        </section>
      </div>

      {canEdit ? (
        <AddStepDialog
          flow={flow}
          position={addAt ?? steps.length + 1}
          open={addAt !== null}
          onOpenChange={(open) => {
            if (!open) setAddAt(null);
          }}
          onSaved={(updated) => {
            saved(updated);
            setAddAt(null);
            announce(t("flows_step_added"));
          }}
        />
      ) : null}
      {canRun ? (
        <StartRunDialog
          flow={flow}
          open={starting}
          onOpenChange={setStarting}
          onStarted={(run) => {
            setStarting(false);
            // The runs list shows the run at once, before it is read again.
            rememberStartedRun(queryClient, flow.id, run);
            void queryClient.invalidateQueries({ queryKey: runKeys.list(flow.id) });
            announce(t("flow_runs_started"));
            // The run's own page follows it while it moves.
            router.push(runHref(routeId, flow.id, run.id));
          }}
        />
      ) : null}
      {mayEdit ? (
        <FlowPackageExportDialog flow={flow} open={exporting} onOpenChange={setExporting} />
      ) : null}
      <ConfirmDialogControlled
        open={confirmUnpublish}
        onOpenChange={(open) => {
          if (!unpublish.isPending) setConfirmUnpublish(open);
        }}
        title={t("flows_unpublish_title")}
        description={t("flows_unpublish_description")}
        confirmLabel={t("unpublish")}
        variant="default"
        pending={unpublish.isPending}
        onConfirm={() => unpublish.mutate()}
      />
    </div>
  );
}
