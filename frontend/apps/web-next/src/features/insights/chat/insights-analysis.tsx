import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkles } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { LeaveConfirmationHandle } from "@/components/composites/leave-confirmation";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { isDerivedSourceRemoved } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { useFocusRescue } from "@/lib/focus-rescue";
import { ChatView, type ActivityState } from "@/features/chat/chat-view";
import { PanelFrame } from "@/features/chat/side-panel/panel-frame";
import type { InsightRange } from "../insights-range";
import { insightCitationReferences } from "./insight-citations";
import {
  insightChatKeys,
  insightConversationApi,
  insightConversationQueryOptions,
  type InsightConversation,
  type InsightTarget
} from "./insights-chat-api";
import { InsightsHistory } from "./insights-history";

/** The analysis on screen. */
type Analysis =
  | {
      kind: "conversation";
      /** Remount key: a new one for every analysis started or opened. */
      key: string;
      sessionId: string | null;
      messages: EneoUIMessage[];
      /** A question was sent, or the analysis was opened with its turns. */
      started: boolean;
      /** Replaces an analysis that went away: its composer takes focus if focus was lost. */
      focusComposer?: boolean;
    }
  /** An earlier analysis on its way from the history. */
  | { kind: "opening"; sessionId: string }
  /** Refused because conversations it was based on have been removed. */
  | { kind: "removed" };

let analysisCounter = 0;

function newAnalysis(focusComposer = false): Analysis {
  analysisCounter += 1;
  return {
    kind: "conversation",
    key: `new-${analysisCounter}`,
    sessionId: null,
    messages: [],
    started: false,
    focusComposer
  };
}

function savedAnalysis(conversation: InsightConversation): Analysis {
  const messages = mapSessionMessages(conversation.messages);
  return {
    kind: "conversation",
    key: conversation.id,
    sessionId: conversation.id,
    messages,
    started: messages.length > 0
  };
}

/** No files: the analysis reads conversations, not attachments. */
const NO_ATTACHMENTS: ChatPartner["allowedAttachments"] = {
  accepted_file_types: [],
  limit: { max_files: 0, max_size: 0 }
};

/** Where the analysis was refused: removed with conversations it was based on. */
function RemovedAnalysis({ onStartNew }: { onStartNew: () => void }) {
  const t = useTranslations();
  return (
    <div className="flex w-full flex-col gap-3 p-4">
      {/* Something that just happened: the title and description are read out at once. */}
      <Banner
        role="alert"
        status="warning"
        title={t("insights_chat_removed_title")}
        description={t("insights_chat_removed_description")}
        endContent={
          <Button
            label={t("insights_chat_start_new")}
            variant="secondary"
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={onStartNew}
          />
        }
      />
    </div>
  );
}

/**
 * "Insiktsanalys", the side panel's content: a conversation with a model
 * that answers by reading the period's conversations through its tools. Its
 * steps show as in any chat, the conversations it cites open in "Utforska
 * konversationer" (the view's `InsightCitationsContext`), and every question
 * carries the period picked when it is sent. Before the first question the
 * panel shows the question field with the earlier analyses under it, to
 * open and continue or delete; "Ny analys" in the header leaves the open one.
 * An analysis built on conversations that have since been removed is
 * removed with them: opening or continuing it says so and offers a new one.
 * Nothing is sent without the person pressing send.
 *
 * It stays mounted while the panel is closed (`hidden`), so the open
 * analysis, a typed question and an answer still streaming are there again
 * when it opens.
 */
export function InsightsAnalysis({
  partner,
  range,
  hidden,
  onClose
}: {
  partner: Pick<ChatPartner, "id"> & { type: InsightTarget["type"] };
  range: InsightRange;
  /** The panel is closed or its page is not on screen: nothing is laid over the page for it. */
  hidden: boolean;
  onClose: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const rescue = useFocusRescue();
  const headingId = useId();
  // Every analysis talks to the same endpoints; each question carries the period picked then.
  const [api] = useState(() => insightConversationApi(range));
  useEffect(() => api.setSelectedRange(range), [api, range]);
  const [analysis, setAnalysis] = useState<Analysis>(() => newAnalysis());
  const [activity, setActivity] = useState<ActivityState | null>(null);
  const leaveConfirmation = useRef<LeaveConfirmationHandle>(null);
  const body = useRef<HTMLDivElement>(null);
  const target: InsightTarget = useMemo(
    () => ({ type: partner.type, id: partner.id }),
    [partner.type, partner.id]
  );

  // Opening an earlier analysis: never from cache, so it shows its latest turns.
  const opening = analysis.kind === "opening" ? analysis.sessionId : null;
  const detail = useQuery({
    ...insightConversationQueryOptions(opening ?? ""),
    enabled: opening !== null
  });
  // The result belongs to the analysis still asked for (the query key).
  if (opening !== null && detail.isSuccess) {
    setAnalysis(savedAnalysis(detail.data));
  } else if (opening !== null && detail.isError && isDerivedSourceRemoved(detail.error)) {
    setAnalysis({ kind: "removed" });
  }

  const removed = analysis.kind === "removed";
  useEffect(() => {
    if (!removed) return;
    // The list leaves a removed analysis out once it is read again.
    void queryClient.invalidateQueries({ queryKey: insightChatKeys.list(target) });
    // What was focused (the question field, the history's row) went with it.
    rescue(() => body.current?.querySelector<HTMLElement>("button") ?? null);
  }, [removed, queryClient, target, rescue]);

  /** Starts a fresh analysis; `focusComposer` when it replaces one that went away. */
  function startNew(focusComposer = false) {
    setAnalysis(newAnalysis(focusComposer));
    setActivity(null);
  }

  /** A typed, unsent question is lost with the analysis: asked first. */
  function leaveAnalysis(action: () => void) {
    if (leaveConfirmation.current) leaveConfirmation.current.confirm(action);
    else action();
  }

  function openAnalysis(sessionId: string) {
    leaveAnalysis(() => {
      setAnalysis({ kind: "opening", sessionId });
      setActivity(null);
      // The history's row goes with the start state: focus moves to the analysis.
      rescue(() => body.current);
    });
  }

  // "Ny analys" once there is an analysis to leave (a removed one offers it itself).
  const canStartNew =
    analysis.kind === "opening" || (analysis.kind === "conversation" && analysis.started);

  // The analysis answers, not the assistant: named for what it does, without
  // the assistant's model, tools, knowledge or attachments.
  const analyst = useMemo<ChatPartner>(
    () => ({
      type: partner.type,
      id: partner.id,
      name: t("insights_chat_partner_name"),
      allowedAttachments: NO_ATTACHMENTS,
      knowledge: [],
      insightEnabled: false
    }),
    [partner.type, partner.id, t]
  );

  let content: ReactNode;
  if (analysis.kind === "removed") {
    content = <RemovedAnalysis onStartNew={() => startNew(true)} />;
  } else if (analysis.kind === "opening") {
    content = (
      <div className="flex w-full flex-col gap-3 p-4">
        {detail.isError ? (
          <ListError
            error={detail.error}
            title={t("insights_chat_open_failed")}
            isRetrying={detail.isFetching}
            onRetry={() => void detail.refetch()}
          />
        ) : (
          <LoadingState rows={4} label={t("insights_chat_opening")} />
        )}
      </div>
    );
  } else {
    content = (
      <ChatView
        key={analysis.key}
        api={api}
        partner={analyst}
        initialSessionId={analysis.sessionId}
        initialMessages={analysis.messages}
        focusComposerIfLost={analysis.focusComposer}
        leaveConfirmationRef={leaveConfirmation}
        activity={activity}
        onActivityChange={setActivity}
        // The answer's activity is laid out in the panel's room, and never
        // over the page while the panel is closed or its page is not shown.
        layout={{ row: body, hidden }}
        references={insightCitationReferences}
        composerLabel={t("insights_chat_ask")}
        placeholder={t("insights_chat_placeholder")}
        onNewConversation={() => startNew(true)}
        onGone={() => setAnalysis({ kind: "removed" })}
        onStartedChange={(value) =>
          setAnalysis((current) =>
            current.kind === "conversation" && current.started !== value
              ? { ...current, started: value }
              : current
          )
        }
        onSessionCreated={(sessionId) => {
          setAnalysis((current) =>
            current.kind === "conversation" ? { ...current, sessionId } : current
          );
          void queryClient.invalidateQueries({ queryKey: insightChatKeys.list(target) });
        }}
        onAnswerFinished={() =>
          void queryClient.invalidateQueries({ queryKey: insightChatKeys.list(target) })
        }
        start={(composer) => (
          <div className="flex w-full flex-col gap-8 p-4">
            <section aria-labelledby={headingId} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <h3 id={headingId} className="text-base font-semibold">
                  {t("insights_chat_ask")}
                </h3>
                <p className="text-ax-text-secondary text-sm">{t("insights_chat_intro")}</p>
              </div>
              {composer}
            </section>
            <InsightsHistory target={target} onOpen={openAnalysis} />
          </div>
        )}
      />
    );
  }

  return (
    <PanelFrame
      icon={<Sparkles className="size-4" />}
      title={t("insights_chat_partner_name")}
      actions={
        canStartNew ? (
          <Button
            label={t("insights_chat_new")}
            variant="ghost"
            size="sm"
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={() => leaveAnalysis(() => startNew(true))}
          />
        ) : null
      }
      switcher={null}
      maximise={null}
      onClose={onClose}
      closeLabel={t("insights_analysis_close")}
    >
      <div
        ref={body}
        tabIndex={-1}
        className="focus-visible:outline-ring flex min-h-0 flex-1 flex-col focus-visible:outline-2 focus-visible:-outline-offset-2"
      >
        {content}
      </div>
    </PanelFrame>
  );
}
