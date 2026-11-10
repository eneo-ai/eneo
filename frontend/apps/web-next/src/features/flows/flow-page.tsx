import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useAnnounce, useMediaQuery } from "@astryxdesign/core/hooks";
import { ResizeHandle, useResizable } from "@astryxdesign/core/Resizable";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery
} from "@tanstack/react-query";
import { goHistory, pushUrl, readUrlState, replaceUrl, useSearchParams } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type CSSProperties
} from "react";
import { flushSync } from "react-dom";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { focusAfterRemoval } from "@/lib/focus-after-removal";
import { useFocusRescue } from "@/lib/focus-rescue";
import { HANDHELD_QUERY } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { useSpaceSections } from "@/features/spaces/frame/use-space-sections";
import { useSpaceDisplayName } from "@/features/spaces/space-display-name";
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
import { parseFlowSearch } from "./flow-search";
import { describeChanges, diffFlowSteps, hasChanges, type StepChange } from "./flow-changes";
import type { ComposerInsert } from "@/features/chat/chat-references";
import { FlowReferences, insertMessage } from "./chat/reference-pill";
import { FlowChatPanel } from "./flow-chat-panel";
import { FlowDraftCheck } from "./flow-draft-check-panel";
import { FlowPackageExportDialog } from "./flow-package-export-dialog";
import { producesLabel, stepLabel } from "./flow-labels";
import { flowRefusalMessage, refusalStep, STALE_REVISION } from "./flow-refusals";
import type { SuggestionDismissal, SuggestionFix } from "./flow-suggestion-item";
import type { SuggestionMeasure } from "./flow-suggestions-section";
import {
  applyFlowSuggestions,
  dismissFlowSuggestion,
  flowSuggestionsQueryOptions,
  forgetMeasuredSuggestions,
  invalidateDefinitionSuggestions,
  measuredBasisText,
  MEASURED_RUNS,
  refetchSuggestionsOnScreen,
  restoreFlowSuggestion,
  SUGGESTION_STALE,
  suggestionsByStep,
  suggestionsOnPage,
  type FlowSuggestion
} from "./flow-suggestions";
import { FlowSettings } from "./flow-settings";
import { FlowStatusBadge } from "./flow-status";
import type { FieldAnchor } from "./editor/field-problems";
import { FlowStepList, showStepCard, stepControlId } from "./flow-step-list";
import { orderWithMove, orderWithout, stepName, stepsInOrder } from "./flow-steps";
import { speakerStepCandidate, speakerStepOption, speakerStepUpdate } from "./speaker-step-offer";
import { FlowPhonePage } from "./flow-phone-page";
import { FlowRunStarter } from "./flow-run-starter";
import { runKeys } from "./runs/runs-api";
import { FlowRunsList } from "./runs/runs-list";

type Notice = {
  key: number;
  status: "error" | "warning" | "info";
  title: string;
  description: string;
  /** The step the refusal is about, which the notice offers to open at `anchor`. */
  step?: FlowStep | null;
  anchor?: FieldAnchor | null;
  /**
   * Unsaved edits held publishing back: the notice goes once they are saved
   * or dropped. Or the core refused to publish the draft on screen.
   */
  cause?: "unsaved" | "publish";
};
type View = "definition" | "chat";
type PageTab = "definition" | "runs";
/** Below lg the chat is one more tab beside the definition's. */
type NarrowTab = PageTab | "chat";
type EditorChange = Omit<FlowEditorUpdate, "expected_revision" | "definition"> & {
  definition?: FlowDefinitionUpdate;
};
type SettingsRequest = NonNullable<ComponentProps<typeof FlowSettings>["openRequest"]>;

const CHAT_WIDTH_STORAGE_KEY = "eneo:flow-chat-width";
/** How long a card the chat touched stays marked. */
const CHAT_CHANGE_MARK_MS = 8000;

/**
 * Whether the flow has any run the caller may see: one content-free row of
 * the runs list, under its key, so a new run refreshes it.
 */
function hasRunsQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: [...runKeys.list(flowId), "any"] as const,
    queryFn: async ({ signal }) => {
      const page = await unwrap(
        browserApi.GET("/api/v1/flows/{id}/runs/", {
          params: { path: { id: flowId }, query: { limit: 1, include_status_counts: false } },
          signal
        })
      );
      return page.items.length > 0;
    }
  });
}

/** The page's address with ?step= set to `stepId`, or without it; other parameters stay. */
function stepUrl(stepId: string | null): URL {
  const url = new URL(window.location.href);
  if (stepId) url.searchParams.set("step", stepId);
  else url.searchParams.delete("step");
  return url;
}

/** After a move the moved step's button keeps focus; at an end, where it is disabled, its twin. */
function focusMoveControl(stepId: string, delta: -1 | 1) {
  requestAnimationFrame(() => {
    const same = document.getElementById(stepControlId(stepId, delta < 0 ? "up" : "down"));
    const other = document.getElementById(stepControlId(stepId, delta < 0 ? "down" : "up"));
    // A disabled Astryx Button is aria-disabled and still focusable.
    const target = same && same.getAttribute("aria-disabled") !== "true" ? same : other;
    target?.focus();
  });
}

/**
 * A flow's page: its definition (settings and steps, each with what it reads
 * and produces) beside its chat. Changes go through the core's editor as one
 * revision-fenced edit each; a refusal is shown above both columns with how
 * to fix it, and a stale draft is reloaded. Publishing freezes the
 * definition until it is unpublished. On a phone the two columns are one
 * view at a time. A suggestion's "Fråga assistenten" and the chat's
 * "Optimera flödet" put a prepared request in the chat's composer (showing
 * the chat first, on a phone); the person sends it. Someone who may view
 * flow traces can have the suggestions measured over the latest runs for
 * the visit ("Räkna med de senaste körningarna"). An editor can dismiss a
 * suggestion for the flow ("Ignorera") and show the dismissed ones again.
 * The header's "Inställningar" and what "Före publicering" says is fixed in
 * the settings open them; the header says while they hold unsaved changes.
 */
function FlowWorkspace({ flowId, onStart }: { flowId: string; onStart: () => void }) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const rescue = useFocusRescue();
  const { routeId, space } = useSpace();
  // What the space offers for transcription, for the settings and the draft check.
  const transcription = {
    models: space.transcription_models,
    services: space.transcription_services ?? []
  };
  const { can } = useAppContext();
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
  const checkHeadingRef = useRef<HTMLHeadingElement>(null);
  const runButtonRef = useRef<HTMLButtonElement>(null);
  const publishButtonRef = useRef<HTMLButtonElement>(null);
  const unpublishButtonRef = useRef<HTMLButtonElement>(null);
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
  // Below lg the chat is a tab under the page's header and tabs. It takes the
  // height the page panel (main, which scrolls) has left under them, so its
  // composer is in view without scrolling the page. A notice above it and
  // the keyboard (which shrinks the panel) change that height.
  const headerRef = useRef<HTMLDivElement>(null);
  const chatRef = useRef<HTMLElement>(null);
  const [chatHeight, setChatHeight] = useState<number | null>(null);
  useLayoutEffect(() => {
    const section = chatRef.current;
    const main = section?.closest("main");
    if (beside || view !== "chat" || !section || !main) return;
    const fit = () => {
      const top =
        section.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop;
      const bottom = Number.parseFloat(getComputedStyle(main).paddingBottom) || 0;
      setChatHeight(Math.round(main.clientHeight - top - bottom));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(main);
    if (headerRef.current) observer.observe(headerRef.current);
    return () => observer.disconnect();
  }, [beside, view]);
  const [addAt, setAddAt] = useState<number | null>(null);
  // Edits on screen that are not saved: the open step's, or the settings form
  // while it is open (the two are never on screen together).
  const [unsavedEdits, setUnsavedEdits] = useState(false);
  const onUnsavedChange = useCallback((unsaved: boolean) => {
    setUnsavedEdits(unsaved);
    // Saved or dropped: "save or cancel first" is no longer true.
    if (!unsaved) setNotice((last) => (last?.cause === "unsaved" ? null : last));
  }, []);
  const [confirmUnpublish, setConfirmUnpublish] = useState(false);
  const [exporting, setExporting] = useState(false);
  // The last ask to bring the settings up, whether their form holds changes
  // not saved, and the problem count "Före publicering" last came to.
  const [settingsRequest, setSettingsRequest] = useState<SettingsRequest>();
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [draftProblems, setDraftProblems] = useState<number | null>(null);
  // The chat's composer while it is on screen (the chat panel reports it).
  const [chatComposer, setChatComposer] = useState<ComposerInsert | null>(null);
  const searchParams = useSearchParams();
  // The open step lives in ?step=, so a refresh or a shared link opens it
  // again (an id the flow does not have shows the list).
  const search = parseFlowSearch({ step: searchParams.get("step"), tab: searchParams.get("tab") });
  const openStepId = search.step ?? null;
  const tab: PageTab = canViewRuns && search.tab === "runs" ? "runs" : "definition";
  // The field the editor moves focus to: a step opened to connect a service,
  // or the field a refusal names (again, while that step is open).
  const [anchorRequest, setAnchorRequest] = useState<{ anchor: FieldAnchor } | null>(null);
  const tabsId = useId();
  const tabId = (id: NarrowTab) => `${tabsId}-tab-${id}`;
  const panelId = `${tabsId}-panel`;
  const chatPanelId = `${tabsId}-chat`;

  /** The tab lives in ?tab=, so a run's page can link back to the list. */
  function selectTab(next: PageTab) {
    const url = new URL(window.location.href);
    if (next === "runs") url.searchParams.set("tab", "runs");
    else url.searchParams.delete("tab");
    replaceUrl(url);
  }

  /** Below lg the chat is a tab of its own: picking another shows the definition's side. */
  function selectNarrowTab(next: NarrowTab) {
    if (next === "chat") {
      setView("chat");
      return;
    }
    setView("definition");
    if (next !== tab) selectTab(next);
  }

  /** Brings the settings up, from the runs or the chat too, at `focus` when given. */
  function openSettings(focus?: SettingsRequest["focus"]) {
    if (tab === "runs") selectTab("definition");
    if (!beside) setView("definition");
    setSettingsRequest((last) => ({ nonce: (last?.nonce ?? 0) + 1, focus }));
  }

  /** A refusal above both columns; a stale draft is reloaded first. */
  const refused = useCallback(
    (error: unknown, title: string, against: readonly FlowStep[], cause?: Notice["cause"]) => {
      const stale = refusalCode(error) === STALE_REVISION;
      if (stale) void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flowId) });
      const about = refusalStep(error, against);
      noticeKey.current += 1;
      setNotice({
        key: noticeKey.current,
        status: stale ? "warning" : "error",
        title: stale ? t("flows_notice_stale_title") : title,
        description: flowRefusalMessage(error, against, t),
        step: about?.step,
        anchor: about?.anchor,
        cause: stale ? undefined : cause
      });
    },
    [flowId, queryClient, t]
  );

  // One FlowReferences for the page: a pill in the chat or in the definition
  // opens the same card, "Visa steget" brings the step's card into view and
  // "Infoga i meddelandet" puts the reference in the chat's composer. On a
  // phone, where one side shows at a time, each first shows its side.
  const composer = useMemo<ComposerInsert | null>(() => {
    if (!chatComposer) return null;
    const showChat = () => {
      if (!beside) flushSync(() => setView("chat"));
    };
    return {
      insertText: (text) => {
        showChat();
        chatComposer.insertText(text);
      },
      insertToken: (token) => {
        showChat();
        chatComposer.insertToken(token);
      }
    };
  }, [beside, chatComposer]);
  const showStep = useCallback(
    (stepId: string) => {
      if (!beside) flushSync(() => setView("definition"));
      return showStepCard(stepId);
    },
    [beside]
  );

  /**
   * "Fråga assistenten" and "Optimera flödet": a prepared request goes into
   * the chat's composer at the caret, steps as pills, the way "Infoga i
   * meddelandet" puts a pill there. It is never sent, and the mode stays.
   * Offered only while the composer is on the page.
   */
  const askChat = composer ? (text: string) => insertMessage(composer, text, flow) : undefined;

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

  // "Åtgärda" and "Åtgärda alla": the core makes the fixes on the draft on
  // screen and answers with the flow, which refetches the step list, the
  // editor and the suggestions by its revision.
  const fix = useMutation({
    mutationFn: (fingerprints: string[]) =>
      applyFlowSuggestions(flowId, flow.draft_revision, fingerprints),
    onSuccess: (result) => {
      saved(result.flow);
      // The fix itself is announced where it was pressed; that some needed
      // no fix is a note beside it.
      const skipped = result.skipped.length;
      if (skipped > 0) {
        noticeKey.current += 1;
        setNotice({
          key: noticeKey.current,
          status: "info",
          title: t("flow_suggestions_skipped_title", { count: skipped }),
          description: t("flow_suggestions_skipped_description", { count: skipped })
        });
      }
    },
    onError: (error) => {
      if (refusalCode(error) === SUGGESTION_STALE) {
        void invalidateDefinitionSuggestions(queryClient, flowId);
      }
      refused(error, t("flow_suggestions_notice_not_fixed"), steps);
    }
  });
  const suggestionFix: SuggestionFix | undefined = canEdit
    ? {
        onFix: async (fingerprints) => {
          try {
            await fix.mutateAsync(fingerprints);
            return true;
          } catch {
            // Refused: the notice above the columns says why.
            return false;
          }
        },
        pending: fix.isPending
      }
    : undefined;

  // "Räkna med de senaste körningarna": the suggestions measured over the
  // latest runs, held for this visit only. Each measured read writes an
  // audit entry on the flow, so one is made on a press and for each new
  // draft revision while the choice holds; nothing else reads one.
  // Held by flow, so another flow opened in this page starts plain.
  const [measuredFlow, setMeasuredFlow] = useState<string | null>(null);
  const canMeasure = canEdit && can("flows_trace");
  const suggestionRuns = canMeasure && measuredFlow === flowId ? MEASURED_RUNS : 0;
  // A flow that has never run has nothing to count: the offer waits for a run.
  const hasRuns = useQuery({ ...hasRunsQueryOptions(flowId), enabled: canMeasure && canViewRuns });
  const measure: SuggestionMeasure | undefined =
    canMeasure && (hasRuns.data === true || suggestionRuns > 0)
      ? {
          runs: suggestionRuns,
          onMeasure: () => {
            // A press reads anew, never an answer from an earlier press.
            forgetMeasuredSuggestions(queryClient, flowId);
            setMeasuredFlow(flowId);
            // The step list and the editor read the same query: this read is
            // the one they find, and once it lands it says what it is based on.
            queryClient
              .query(flowSuggestionsQueryOptions(flowId, flow.draft_revision, MEASURED_RUNS))
              .then(
                (answer) => {
                  if (answer.runs) announce(measuredBasisText(answer.runs, answer.items.length, t));
                },
                // Refused or failed: the step list says why and offers to try again.
                () => undefined
              );
          },
          onPlain: () => {
            setMeasuredFlow(null);
            announce(t("flow_suggestions_runs_plain_done"));
          }
        }
      : undefined;
  // The measured answers stay for the visit (no remount reads them again)
  // and go with it.
  useEffect(() => () => forgetMeasuredSuggestions(queryClient, flowId), [flowId, queryClient]);

  // "Ignorera" and "Visa igen": a dismissal is the flow's, for every editor
  // of it, and leaves the draft revision as it is, so the suggestions on
  // screen are read again once it is saved (measured once more only while
  // the page measures; no other measured answer is read). The pressed
  // button stays busy until the row has left. "Visa ignorerade" is held for
  // the visit, by flow, as the measured view is.
  const [dismissedShownFlow, setDismissedShownFlow] = useState<string | null>(null);
  const refreshSuggestions = () =>
    refetchSuggestionsOnScreen(queryClient, flowId, flow.draft_revision, suggestionRuns);
  const dismissal = useMutation({
    mutationFn: async ({
      suggestion,
      restore
    }: {
      suggestion: FlowSuggestion;
      restore: boolean;
    }) => {
      if (restore) await restoreFlowSuggestion(flowId, suggestion.fingerprint);
      else await dismissFlowSuggestion(flowId, suggestion);
    },
    onSuccess: () => {
      setNotice(null);
      return refreshSuggestions();
    },
    onError: (error, { restore }) => {
      // The draft no longer has the suggestion: its plain answer is read again.
      if (refusalCode(error) === SUGGESTION_STALE) {
        void invalidateDefinitionSuggestions(queryClient, flowId);
      }
      refused(
        error,
        restore
          ? t("flow_suggestions_notice_not_restored")
          : t("flow_suggestions_notice_not_dismissed"),
        steps
      );
    }
  });
  const suggestionDismissal: SuggestionDismissal | undefined = canEdit
    ? {
        onDismiss: async (suggestion) => {
          try {
            await dismissal.mutateAsync({ suggestion, restore: false });
            return true;
          } catch {
            // Refused: the notice above the columns says why.
            return false;
          }
        },
        onRestore: async (suggestion) => {
          try {
            await dismissal.mutateAsync({ suggestion, restore: true });
            return true;
          } catch {
            return false;
          }
        },
        busy: dismissal.isPending ? (dismissal.variables?.suggestion.fingerprint ?? null) : null,
        showDismissed: dismissedShownFlow === flowId,
        onShowDismissed: (show) => setDismissedShownFlow(show ? flowId : null)
      }
    : undefined;

  const publish = useMutation({
    mutationFn: () => publishFlow(flow),
    onSuccess: (updated) => {
      saved(updated);
      announce(t("flows_published", { version: updated.published_version ?? "" }));
      // Publicera has gone; what the flow is for now takes its place.
      rescue(() => runButtonRef.current ?? unpublishButtonRef.current);
    },
    onError: (error) => refused(error, t("flows_notice_not_published"), steps, "publish")
  });

  const unpublish = useMutation({
    mutationFn: () => unpublishFlow(flow),
    onSuccess: (updated) => {
      saved(updated);
      setConfirmUnpublish(false);
      announce(t("flows_unpublished"));
      rescue(() => publishButtonRef.current);
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
      // browser has one, the person has not asked for less motion and the
      // tab is on screen: a hidden document gets no transition (the browser
      // skips it, and says so by rejecting the transition's promises).
      if (
        changes &&
        hasChanges(changes) &&
        typeof document.startViewTransition === "function" &&
        document.visibilityState === "visible" &&
        !window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ) {
        const transition = document.startViewTransition(apply);
        // A transition the browser skips after all (the tab hidden meanwhile)
        // still applies the change; its promises reject, which is not news.
        transition.ready.catch(() => undefined);
        transition.finished.catch(() => undefined);
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

  /**
   * Publishes the saved draft. A draft the page already knows cannot be
   * published is not sent: a notice says why (it is an alert, so it is read
   * out too). Edits not yet saved hold it back until saved or dropped; an
   * empty list or a problem also takes focus to what to fix (the step list,
   * or "Före publicering").
   */
  function requestPublish() {
    if (publish.isPending) return;
    const hold = (description: string, status: Notice["status"], cause?: Notice["cause"]) => {
      noticeKey.current += 1;
      setNotice({
        key: noticeKey.current,
        status,
        title: t("flows_notice_not_published"),
        description,
        cause
      });
    };
    if (unsavedEdits) {
      hold(t("flows_publish_unsaved"), "error", "unsaved");
      return;
    }
    if (steps.length === 0) {
      hold(t("flows_publish_needs_steps"), "warning");
      stepsHeadingRef.current?.focus();
      return;
    }
    if (draftProblems) {
      hold(t("flow_editor_tools_check_problems", { count: draftProblems }), "warning");
      checkHeadingRef.current?.focus();
      return;
    }
    publish.mutate();
  }

  /**
   * Opens a step as a native history entry, at `anchor` when given; the editor
   * owns the unsaved-edit decision.
   */
  function openStep(step: Pick<FlowStep, "id">, anchor: FieldAnchor | null = null) {
    if (!step.id) return;
    setAnchorRequest(anchor ? { anchor } : null);
    pushUrl(stepUrl(step.id), {
      state: { flowStepDepth: (readUrlState().flowStepDepth ?? 0) + 1 }
    });
  }

  /** Return across the steps visited here; a direct link replaces only its own entry. */
  function closeStep() {
    const depth = readUrlState().flowStepDepth ?? 0;
    if (depth > 0) goHistory(-depth);
    else replaceUrl(stepUrl(null));
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
      toast.success(t("flows_settings_saved"));
      return true;
    } catch {
      return false;
    }
  }

  const openedStep = openStepId ? steps.find((step) => step.id === openStepId) : undefined;
  const openedIndex = openedStep ? steps.indexOf(openedStep) : -1;
  // The editor's step menu marks the steps with suggestions: the same read
  // the step list and the editor make, so it costs no request of its own.
  const menuSuggestions = useQuery({
    ...flowSuggestionsQueryOptions(flowId, flow.draft_revision, suggestionRuns),
    enabled: canEdit && openedStep !== undefined
  });
  const suggestionsPerStep = suggestionsByStep(
    suggestionsOnPage(canEdit ? menuSuggestions.data?.items : [], steps).shown
  );
  // The step view hides the tabs: "Alla steg" is its way back to the list.
  const editorOpen = tab === "definition" && openedStep?.id !== undefined;
  const showTabs = canViewRuns && !editorOpen;
  // Below lg the definition's side is a tab's panel while it shows, and the
  // chat is the panel of its own tab.
  const panelIsTabbed = beside ? showTabs : view === "definition";
  const menuSteps = steps.flatMap((step) =>
    step.id
      ? [
          {
            id: step.id,
            label: stepLabel(step, t),
            kind: producesLabel(step, t),
            suggestions: suggestionsPerStep.get(step.id)?.length ?? 0
          }
        ]
      : []
  );
  const neighbour = (step: FlowStep | undefined) =>
    step?.id
      ? {
          id: step.id,
          name: stepName(step) ?? t("flows_step_label_unnamed", { order: step.step_order })
        }
      : null;

  const previousStep = useRef<string | null>(null);
  useLayoutEffect(() => {
    const previous = previousStep.current;
    const current = editorOpen ? openStepId : null;
    previousStep.current = current;
    if (current === previous) return;
    if (current) editorRef.current?.focus();
    else if (previous) {
      const frame = requestAnimationFrame(() =>
        document.getElementById(stepControlId(previous, "open"))?.focus()
      );
      return () => cancelAnimationFrame(frame);
    }
  }, [editorOpen, openStepId]);
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

  // The action for what the flow is now goes first: a run of a published
  // flow, publishing a draft. Exporting is rare, so it waits in "Fler åtgärder".
  // Publicera is the page's primary action only once it can succeed: an empty
  // draft's is adding a step, and one with problems is fixing them.
  const publishReady = steps.length > 0 && !draftProblems;
  // "Inställningar" leads to the settings from where they are not on screen:
  // the runs, or the chat below lg. Beside them their section has its own.
  const settingsElsewhere = !editorOpen && (tab === "runs" || (!beside && view === "chat"));
  const actions = (
    <div className="flex flex-wrap items-center gap-2">
      {canRun ? (
        <Button
          ref={runButtonRef}
          label={t("flow_runs_start")}
          variant="primary"
          onClick={onStart}
        />
      ) : null}
      {canPublish && !isPublished ? (
        <Button
          ref={publishButtonRef}
          label={t("publish")}
          variant={publishReady ? "primary" : "secondary"}
          onClick={requestPublish}
          // The label stays while it publishes (isLoading would leave an
          // empty button); requestPublish ignores a press meanwhile.
          icon={
            publish.isPending ? <Spinner size="sm" shade="inherit" aria-hidden="true" /> : undefined
          }
          aria-busy={publish.isPending || undefined}
        />
      ) : null}
      {settingsElsewhere ? (
        <Button label={t("flows_settings_heading")} onClick={() => openSettings()} />
      ) : null}
      {canPublish && isPublished ? (
        <Button
          ref={unpublishButtonRef}
          label={t("unpublish")}
          // The confirmation's own button shows the work.
          onClick={() => setConfirmUnpublish(true)}
        />
      ) : null}
      {mayEdit ? (
        <MoreMenu
          label={t("flow_page_more_actions")}
          alignment="end"
          items={[{ label: t("flow_page_export_package"), onClick: () => setExporting(true) }]}
        />
      ) : null}
    </div>
  );

  const settings = (
    <FlowSettings
      key="settings"
      flow={flow}
      canEdit={canEdit}
      transcription={transcription}
      onSave={saveSettings}
      onEditingChange={onUnsavedChange}
      openRequest={settingsRequest}
      classification={space.security_classification}
      onDirtyChange={setSettingsDirty}
    />
  );
  const stepList = (
    <FlowStepList
      key="steps"
      flowId={flow.id}
      draftRevision={flow.draft_revision}
      steps={steps}
      canEdit={canEdit}
      mayEdit={mayEdit}
      changes={chatChanges}
      onAskChat={askChat}
      suggestionFix={suggestionFix}
      dismissal={suggestionDismissal}
      measure={measure}
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
  );
  // One order, empty or not: what stands before publishing, the steps (what
  // a flow is built from), then its settings. Until it has a step there is
  // nothing to check. Keyed, so the parts stay mounted when the first step
  // lands (an open settings form keeps what is typed in it).
  const definition = [
    canEdit && steps.length > 0 ? (
      <FlowDraftCheck
        key="check"
        flow={flow}
        suggestionRuns={suggestionRuns}
        transcription={transcription}
        onOpenStep={openStep}
        onRepair={repairReference}
        onOpenSettings={openSettings}
        onProblemCount={setDraftProblems}
        headingRef={checkHeadingRef}
        refused={notice?.cause === "publish"}
      />
    ) : null,
    stepList,
    settings
  ];

  return (
    <FlowReferences
      flow={flow}
      onShowStep={showStep}
      onConnectStep={(stepId, anchor) => openStep({ id: stepId }, anchor)}
      composer={composer}
    >
      <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">
        <div
          ref={headerRef}
          className="border-ax-border flex flex-col gap-3 border-b px-6 pt-4 pb-3 max-lg:border-b-0 max-lg:pb-1"
        >
          <PageHeader
            title={flow.name}
            description={flow.description?.trim() || undefined}
            breadcrumbs={[
              { label: spaceName, href: spaceLandingHref(sections, routeId) },
              { label: t("flows"), href: `/spaces/${routeId}/flows` },
              // The open step is a crumb of its own; the way back to the
              // list is the editor's "Alla steg", which asks about unsaved
              // edits first, so the flow's crumb is no link while it is open.
              ...(openedStep && tab === "definition"
                ? [{ label: flow.name }, { label: stepLabel(openedStep, t), current: true }]
                : [{ label: flow.name, current: true }])
            ]}
            actions={
              <>
                <FlowStatusBadge publishedVersion={flow.published_version} />
                {settingsDirty ? (
                  <Badge variant="warning" label={t("flow_page_settings_unsaved")} />
                ) : null}
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
              endContent={
                notice.step?.id && notice.step.id !== openedStep?.id ? (
                  <Button
                    label={t("flow_editor_tools_check_open_step")}
                    aria-label={t("flow_editor_tools_check_open_step_named", {
                      step: stepLabel(notice.step, t)
                    })}
                    size="sm"
                    onClick={() => notice.step && openStep(notice.step, notice.anchor)}
                  />
                ) : notice.step?.id && notice.anchor ? (
                  <Button
                    label={t("flows_notice_go_to_field")}
                    size="sm"
                    onClick={() => notice.anchor && setAnchorRequest({ anchor: notice.anchor })}
                  />
                ) : undefined
              }
              isDismissable
              dismissLabel={t("flows_notice_dismiss")}
              onDismiss={() => setNotice(null)}
            />
          ) : null}
        </div>
        {/* Below lg one row of tabs holds the definition, the runs and the
            chat (the runs leave while a step is open). It stays in reach
            while the definition scrolls, except where a bar of its own
            already sticks there: a phone's layout (the space's PageBar) and
            an open step (its bar). data-page-bar keeps focus and scrolled-to
            content clear of it (app-shell.tsx). */}
        {beside ? null : (
          <div
            {...(editorOpen ? {} : { "data-page-bar": "" })}
            className={cn("bg-ax-surface z-10 px-6", !editorOpen && "wide:sticky wide:top-0")}
          >
            <TabList
              role="tablist"
              aria-label={t("flow_runs_tabs_label")}
              value={view === "chat" ? "chat" : tab}
              onChange={(value) => selectNarrowTab(value as NarrowTab)}
              hasDivider
            >
              <Tab
                id={tabId("definition")}
                value="definition"
                label={t("flow_runs_tab_definition")}
                panelId={panelId}
              />
              {showTabs ? (
                <Tab
                  id={tabId("runs")}
                  value="runs"
                  label={t("flow_runs_tab_runs")}
                  panelId={panelId}
                />
              ) : null}
              <Tab
                id={tabId("chat")}
                value="chat"
                label={t("flows_view_chat")}
                panelId={chatPanelId}
              />
            </TabList>
          </div>
        )}

        <div
          ref={beside ? row : null}
          className="flex min-w-0 flex-col lg:min-h-0 lg:flex-1 lg:flex-row"
        >
          <section
            aria-label={t("flows_view_definition")}
            className={cn(
              "flex min-w-0 flex-col lg:min-h-0 lg:flex-1",
              // An open step owns the scrolling, between its bar and its
              // save bar; the list and the runs scroll here, under the tabs.
              editorOpen ? "lg:overflow-hidden" : "gap-6 px-6 py-5 lg:overflow-y-auto",
              view !== "definition" && "max-lg:hidden"
            )}
          >
            {beside && showTabs ? (
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
              role={panelIsTabbed ? "tabpanel" : undefined}
              id={panelId}
              aria-labelledby={panelIsTabbed ? tabId(tab) : undefined}
              className={cn("flex min-w-0 flex-col", editorOpen ? "lg:min-h-0 lg:flex-1" : "gap-6")}
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
                  className="focus-visible:outline-ring flex min-h-0 min-w-0 flex-1 flex-col focus-visible:outline-2 focus-visible:-outline-offset-2"
                >
                  <FlowStepEditor
                    flow={flow}
                    stepId={openedStep.id}
                    anchorRequest={anchorRequest}
                    readOnly={!canEdit}
                    onAskChat={askChat}
                    suggestionFix={suggestionFix}
                    suggestionDismissal={suggestionDismissal}
                    suggestionRuns={suggestionRuns}
                    onSaved={(updated) => {
                      saved(updated);
                      announce(t("flows_step_saved", { step: stepLabel(openedStep, t) }));
                    }}
                    onCancel={closeStep}
                    onUnsavedChange={onUnsavedChange}
                    navigation={{
                      position: openedIndex + 1,
                      count: steps.length,
                      previous: neighbour(steps[openedIndex - 1]),
                      next: neighbour(steps[openedIndex + 1]),
                      steps: menuSteps,
                      onGo: (id) => openStep({ id })
                    }}
                  />
                </section>
              ) : (
                <>
                  {isPublished ? (
                    // The header's badge names the version; this says what it means here.
                    <Banner
                      status="info"
                      title={t("flows_published_read_only")}
                      description={
                        canUnpublishToEdit ? t("flows_published_description") : undefined
                      }
                      collapsible={false}
                    />
                  ) : null}
                  {definition}
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
            ref={chatRef}
            id={chatPanelId}
            role={beside ? undefined : "tabpanel"}
            aria-labelledby={beside ? undefined : tabId("chat")}
            aria-label={beside ? t("flows_chat_heading") : undefined}
            style={
              beside
                ? { width: chat.size }
                : chatHeight !== null
                  ? ({ "--flow-chat-h": `${chatHeight}px` } as CSSProperties)
                  : undefined
            }
            className={cn(
              "border-ax-border flex h-[var(--flow-chat-h,85dvh)] min-h-[28rem] min-w-0 flex-col border-t lg:h-auto lg:min-h-0 lg:shrink-0 lg:border-t-0",
              view !== "chat" && "max-lg:hidden"
            )}
          >
            <FlowChatPanel
              flow={flow}
              onFlowMayHaveChanged={() => void refreshFromChat()}
              onRefused={(error, title) => refused(error, title, steps)}
              onComposer={setChatComposer}
              onAskChat={askChat}
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
              const position = addAt ?? steps.length + 1;
              saved(updated);
              setAddAt(null);
              announce(t("flows_step_added"));
              // The first step's "Lägg till steg" leaves with the empty list: focus goes to the step.
              const added = stepsInOrder(updated).find((step) => step.step_order === position);
              rescue(
                () =>
                  (added?.id ? document.getElementById(stepControlId(added.id, "open")) : null) ??
                  stepsHeadingRef.current
              );
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
    </FlowReferences>
  );
}

/**
 * A flow's page. A phone (a screen you touch and hold in a hand, upright or
 * sideways) runs flows and reads their runs and builds none, so it gets the
 * lean page; everyone else the workspace.
 * A desktop window dragged below 768 px keeps the workspace, and what is being
 * edited in it.
 */
export function FlowPage({ flowId }: { flowId: string }) {
  const handheld = useMediaQuery(HANDHELD_QUERY);
  // The start form is here, not in either page: turning a phone across 768 px swaps the pages,
  // and a recording in the form goes on.
  const [starting, setStarting] = useState(false);
  const onStart = () => setStarting(true);
  return (
    <>
      {handheld ? (
        <FlowPhonePage flowId={flowId} onStart={onStart} />
      ) : (
        <FlowWorkspace flowId={flowId} onStart={onStart} />
      )}
      <FlowRunStarter flowId={flowId} open={starting} onOpenChange={setStarting} />
    </>
  );
}
