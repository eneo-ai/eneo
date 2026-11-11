import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Plus, ThumbsDown, ThumbsUp } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { LeaveConfirmationHandle } from "@/components/composites/leave-confirmation";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { isDerivedSourceRemoved, unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { useFocusRescue } from "@/lib/focus-rescue";
import { ExploreConversationsDialog } from "@/features/insights/explore-conversations-dialog";
import {
  insightCitationReferences,
  InsightCitationsContext
} from "@/features/insights/chat/insight-citations";
import {
  insightChatKeys,
  insightConversationApi,
  insightConversationQueryOptions,
  type InsightConversation,
  type InsightTarget
} from "@/features/insights/chat/insights-chat-api";
import { InsightsHistory } from "@/features/insights/chat/insights-history";
import {
  DEFAULT_INSIGHT_DAYS,
  insightPartnerQuery,
  insightRangeOfDays,
  insightRangeParams,
  type InsightRange
} from "@/features/insights/insights-range";
import { InsightsRangePicker } from "@/features/insights/insights-range-picker";
import { ChatView, type ActivityState } from "./chat-view";

type InsightPartner = ChatPartner & { type: InsightTarget["type"] };

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

function Stat({ label, value }: { label: ReactNode; value: number }) {
  return (
    <div className="border-ax-border rounded-ax-container border p-4">
      <dt className="text-ax-text-secondary inline-flex items-center gap-1.5 text-sm">{label}</dt>
      <dd className="mt-1 text-3xl font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * The period's conversation and question counts, how the answers were rated,
 * and the conversations themselves behind "Utforska konversationer".
 */
function InsightsOverview({
  partner,
  range,
  onExplore
}: {
  partner: InsightPartner;
  range: InsightRange;
  onExplore: () => void;
}) {
  const t = useTranslations();
  const params = insightRangeParams(range);
  const stats = useQuery({
    queryKey: [
      "conversation-insights",
      "stats",
      partner.type,
      partner.id,
      params.fromDate,
      params.toDate
    ],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/analysis/conversation-insights/", {
          params: {
            query: {
              start_time: params.startTime,
              end_time: params.endTime,
              ...insightPartnerQuery(partner)
            }
          },
          signal
        })
      )
  });

  return (
    <div className="flex flex-col gap-5">
      <QueryStateBoundary query={stats} rows={2}>
        {(data) => (
          <dl className="grid gap-3 sm:grid-cols-2">
            <Stat label={t("total_conversations")} value={data.total_conversations} />
            <Stat label={t("total_questions")} value={data.total_questions} />
            {/* Ratings of single answers; a rating of a whole conversation is not counted. */}
            <Stat
              label={
                <>
                  <ThumbsUp aria-hidden="true" className="text-ax-success size-4" />
                  {t("feedback_good_answers")}
                </>
              }
              value={data.feedback.positive}
            />
            <Stat
              label={
                <>
                  <ThumbsDown aria-hidden="true" className="text-ax-error size-4" />
                  {t("feedback_bad_answers")}
                </>
              }
              value={data.feedback.negative}
            />
          </dl>
        )}
      </QueryStateBoundary>

      <div className="border-ax-border rounded-ax-container flex flex-wrap items-center justify-between gap-3 border p-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{t("explore_conversations")}</p>
          <p className="text-ax-text-secondary text-sm">{t("view_all_conversations_users_had")}</p>
        </div>
        <Button
          label={t("explore_conversations")}
          variant="secondary"
          icon={<History className="size-4" aria-hidden="true" />}
          onClick={onExplore}
        />
      </div>
    </div>
  );
}

/** Where the analysis was refused: removed with conversations it was based on. */
function RemovedAnalysis({ onStartNew }: { onStartNew: () => void }) {
  const t = useTranslations();
  return (
    <div className="mx-auto flex w-full max-w-[712px] flex-col gap-3 px-4 py-6">
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
 * Insikter for an assistant or group chat: a period (the last 30 days to
 * begin with) above everything, its conversation and question counts and how
 * the answers were rated, the conversations themselves behind "Utforska
 * konversationer", and an analysis to ask about them. The analysis is a
 * conversation with a model that answers by reading those conversations
 * through its tools: its steps show as in any chat, the conversations it
 * cites open beside the list in "Utforska konversationer", and every
 * question carries the period picked when it is sent. Earlier analyses are
 * listed under the question field, to open and continue or delete. An
 * analysis built on conversations that have since been removed is removed
 * with them: opening or continuing it says so and offers a new one.
 */
export function InsightsPanel({ partner }: { partner: InsightPartner }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const rescue = useFocusRescue();
  const headingId = useId();
  const [range, setRange] = useState<InsightRange>(() => insightRangeOfDays(DEFAULT_INSIGHT_DAYS));
  // Every analysis talks to the same endpoints; each question carries the period picked then.
  const [api] = useState(() => insightConversationApi(range));
  useEffect(() => api.setSelectedRange(range), [api, range]);
  const [explore, setExplore] = useState<{ sessionId: string | null } | null>(null);
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

  const overview = (
    <InsightsOverview
      partner={partner}
      range={range}
      onExplore={() => setExplore({ sessionId: null })}
    />
  );

  let content: ReactNode;
  if (analysis.kind === "removed") {
    content = <RemovedAnalysis onStartNew={() => startNew(true)} />;
  } else if (analysis.kind === "opening") {
    content = (
      <div className="mx-auto flex w-full max-w-[712px] flex-col gap-3 px-4 py-6">
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
        lead={<div className="mx-auto w-full max-w-[712px] px-4 pt-6 pb-2">{overview}</div>}
        start={(composer) => (
          <div className="mx-auto flex w-full max-w-[712px] flex-col gap-8 px-4 py-6">
            {overview}
            <section aria-labelledby={headingId} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <h2 id={headingId} className="text-base font-semibold">
                  {t("insights_chat_ask")}
                </h2>
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
    <InsightCitationsContext value={(sessionId) => setExplore({ sessionId })}>
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="border-ax-border shrink-0 border-b px-4 py-3">
          <div className="mx-auto flex w-full max-w-[712px] flex-wrap items-end justify-between gap-3">
            <div className="min-w-0 flex-1 sm:max-w-80">
              <InsightsRangePicker value={range} onChange={setRange} compact />
            </div>
            {canStartNew && (
              <Button
                label={t("insights_chat_new")}
                variant="secondary"
                icon={<Plus className="size-4" aria-hidden="true" />}
                onClick={() => leaveAnalysis(() => startNew(true))}
              />
            )}
          </div>
        </div>
        <div
          ref={body}
          tabIndex={-1}
          className="focus-visible:outline-ring flex min-h-0 flex-1 flex-col focus-visible:outline-2 focus-visible:-outline-offset-2"
        >
          {content}
        </div>
      </div>
      {explore && (
        <ExploreConversationsDialog
          key={explore.sessionId ?? "list"}
          partner={partner}
          range={range}
          isOpen
          initialSessionId={explore.sessionId}
          onOpenChange={(open) => {
            if (!open) setExplore(null);
          }}
        />
      )}
    </InsightCitationsContext>
  );
}
