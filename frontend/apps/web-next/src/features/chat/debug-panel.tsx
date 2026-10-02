"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, RotateCcw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { modelDisplayName } from "@/lib/models/model-display-name";
import { CopyableValue, DebugSection } from "./debug-section";
import { SkillActivationSection } from "./debug-skills";
import {
  listDebugTurns,
  projectTurnDebugDetails,
  type ChatTurnDiagnostics,
  type PersistedMessage,
  type TurnDebugDetails
} from "./turn-debug";

/** How the Felsök tab is wired: the saved conversation and turn navigation. */
export type DebugTabConfig = {
  sessionId: string;
  /** Opens another saved turn of the conversation in the panel. */
  onSelectTurn: (messageId: string) => void;
};

function TurnSummary({ details }: { details: TurnDebugDetails }) {
  const t = useTranslations();
  const format = useFormatter();
  return (
    <DebugSection title={t("chat_debug_generic_summary")}>
      <dl className="grid grid-cols-1 gap-x-5 gap-y-3 text-sm sm:grid-cols-2">
        <div className="min-w-0">
          <dt className="text-ax-text-secondary text-xs">{t("chat_debug_model")}</dt>
          <dd className="mt-0.5 font-medium break-words">
            {details.model
              ? modelDisplayName({ name: details.model.name, nickname: details.model.nickname })
              : t("chat_debug_unknown")}
          </dd>
        </div>
        {details.createdAt && (
          <div>
            <dt className="text-ax-text-secondary text-xs">{t("chat_debug_sent_at")}</dt>
            <dd className="mt-0.5 font-medium tabular-nums">
              <ClientTime value={details.createdAt} format="date_time" />
            </dd>
          </div>
        )}
        <div>
          <dt className="text-ax-text-secondary text-xs">{t("chat_debug_input_tokens")}</dt>
          <dd className="mt-0.5 font-medium tabular-nums">{format.number(details.inputTokens)}</dd>
        </div>
        <div>
          <dt className="text-ax-text-secondary text-xs">{t("chat_debug_output_tokens")}</dt>
          <dd className="mt-0.5 font-medium tabular-nums">{format.number(details.outputTokens)}</dd>
        </div>
        {details.model && (
          <>
            <CopyableValue label={t("chat_debug_model_route")} value={details.model.route} />
            <CopyableValue label={t("chat_debug_model_id")} value={details.model.id} />
          </>
        )}
      </dl>
    </DebugSection>
  );
}

function ToolsSection({ tools }: { tools: TurnDebugDetails["tools"] }) {
  const t = useTranslations();
  const format = useFormatter();
  return (
    <DebugSection title={t("chat_debug_tools")} count={tools.length} defaultOpen={tools.length > 0}>
      {tools.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("chat_debug_no_tools")}</p>
      ) : (
        <ol className="flex flex-col gap-1">
          {tools.map((tool) => (
            <li
              key={tool.order}
              className="border-ax-border rounded-ax-element min-w-0 border px-3 py-2.5"
            >
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium break-words">
                    <span className="text-ax-text-secondary tabular-nums">
                      {t("chat_debug_tool_order", { order: tool.order })}
                    </span>{" "}
                    · {tool.isSkill ? `Skill · ${tool.toolName}` : tool.toolName}
                  </p>
                  <p className="text-ax-text-secondary mt-0.5 text-xs break-words">
                    {tool.isSkill ? t("skills") : tool.serverName}
                  </p>
                </div>
                <Badge variant="neutral" label={tool.status ?? t("chat_debug_status_unknown")} />
              </div>
              {tool.usage && (
                <dl
                  className="border-ax-border mt-2 grid grid-cols-2 gap-x-5 gap-y-2 border-t pt-2 text-sm"
                  aria-label={t("chat_debug_tool_usage")}
                >
                  {tool.usage.model && (
                    <div className="min-w-0">
                      <dt className="text-ax-text-secondary text-xs">{t("chat_debug_model")}</dt>
                      <dd className="mt-0.5 font-medium break-words">{tool.usage.model}</dd>
                    </div>
                  )}
                  {tool.usage.provider && (
                    <div className="min-w-0">
                      <dt className="text-ax-text-secondary text-xs">{t("chat_debug_provider")}</dt>
                      <dd className="mt-0.5 font-medium break-words">{tool.usage.provider}</dd>
                    </div>
                  )}
                  {tool.usage.inputTokens !== null && (
                    <div>
                      <dt className="text-ax-text-secondary text-xs">
                        {t("chat_debug_input_tokens")}
                      </dt>
                      <dd className="mt-0.5 font-medium tabular-nums">
                        {format.number(tool.usage.inputTokens)}
                      </dd>
                    </div>
                  )}
                  {tool.usage.outputTokens !== null && (
                    <div>
                      <dt className="text-ax-text-secondary text-xs">
                        {t("chat_debug_output_tokens")}
                      </dt>
                      <dd className="mt-0.5 font-medium tabular-nums">
                        {format.number(tool.usage.outputTokens)}
                      </dd>
                    </div>
                  )}
                </dl>
              )}
            </li>
          ))}
        </ol>
      )}
    </DebugSection>
  );
}

function KnowledgeSection({ knowledge }: { knowledge: TurnDebugDetails["knowledge"] }) {
  const t = useTranslations();
  return (
    <DebugSection
      title={t("chat_debug_knowledge")}
      count={knowledge.length}
      defaultOpen={knowledge.length > 0}
    >
      {knowledge.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("chat_debug_no_knowledge")}</p>
      ) : (
        <ol className="flex flex-col gap-1">
          {knowledge.map((reference) => (
            <li
              key={reference.order}
              className="border-ax-border rounded-ax-element min-w-0 border px-3 py-2.5"
            >
              <p className="text-sm font-medium break-words">
                <span className="text-ax-text-secondary tabular-nums">
                  {t("chat_debug_reference_order", { order: reference.order })}
                </span>{" "}
                · {reference.title}
              </p>
              {reference.uri && (
                <dl className="mt-1.5">
                  <CopyableValue label={t("chat_debug_uri")} value={reference.uri} />
                </dl>
              )}
            </li>
          ))}
        </ol>
      )}
    </DebugSection>
  );
}

function FilesSection({ files }: { files: TurnDebugDetails["files"] }) {
  const t = useTranslations();
  return (
    <DebugSection title={t("chat_debug_files")} count={files.length} defaultOpen={files.length > 0}>
      {files.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("chat_debug_no_files")}</p>
      ) : (
        <ol className="flex flex-col gap-1">
          {files.map((file) => (
            <li
              key={file.order}
              className="border-ax-border rounded-ax-element flex min-w-0 items-start justify-between gap-3 border px-3 py-2.5"
            >
              <span className="min-w-0 text-sm break-all">{file.name}</span>
              <Badge
                variant="neutral"
                label={
                  file.kind === "input"
                    ? t("chat_debug_file_input")
                    : t("chat_debug_file_generated")
                }
              />
            </li>
          ))}
        </ol>
      )}
    </DebugSection>
  );
}

function TurnDiagnostics({
  message,
  diagnostics
}: {
  message: PersistedMessage;
  diagnostics: ChatTurnDiagnostics;
}) {
  const t = useTranslations();
  const details = projectTurnDebugDetails(
    message,
    diagnostics.skill_activation
      ? {
          id: diagnostics.skill_activation.selected_model_id,
          route: diagnostics.skill_activation.selected_model_route
        }
      : undefined
  );
  return (
    <>
      <TurnSummary details={details} />
      <ToolsSection tools={details.tools} />
      <KnowledgeSection knowledge={details.knowledge} />
      <FilesSection files={details.files} />
      {diagnostics.skill_activation ? (
        <SkillActivationSection evidence={diagnostics.skill_activation} />
      ) : (
        <section
          aria-label={t("chat_debug_legacy_skills_title")}
          className="flex flex-col gap-1 py-4"
        >
          <h3 className="text-sm font-semibold">{t("chat_debug_legacy_skills_title")}</h3>
          <p className="text-ax-text-secondary max-w-[65ch] text-sm leading-5">
            {t("chat_debug_legacy_skills_description")}
          </p>
        </section>
      )}
    </>
  );
}

/**
 * The Felsök tab of the Aktivitet panel (users with `assistant_debug`): what
 * one saved turn ran with — model and route, tokens, tool calls with their
 * provider usage, knowledge references, files and the Skill activation
 * evidence. Loaded only when the tab opens: the saved conversation (its
 * persisted message carries what the stream does not, like the model route
 * and tool metadata) and the turn's diagnostics. Other saved turns are a
 * step away with the previous/next buttons.
 */
export function DebugTabPanel({
  messageId,
  sessionId,
  onSelectTurn
}: DebugTabConfig & { messageId: string }) {
  const t = useTranslations();
  const announce = useAnnounce();

  // Never served from cache: a turn that was still being saved when the tab
  // opened must show up on the next look.
  const session = useQuery({
    queryKey: ["chat-debug", "session", sessionId],
    staleTime: 0,
    gcTime: 0,
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/", {
          params: { path: { session_id: sessionId } },
          signal
        })
      )
  });
  const diagnostics = useQuery({
    queryKey: ["chat-debug", "diagnostics", sessionId, messageId],
    staleTime: 0,
    gcTime: 0,
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/messages/{message_id}/diagnostics/", {
          params: { path: { session_id: sessionId, message_id: messageId } },
          signal
        })
      )
  });

  const loaded = session.isSuccess && diagnostics.isSuccess;
  const announcedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!loaded || announcedFor.current === messageId) return;
    announcedFor.current = messageId;
    announce(t("chat_debug_loaded"));
  }, [loaded, messageId, announce, t]);

  const turns = listDebugTurns(session.data?.messages ?? []);
  const index = turns.findIndex((turn) => turn.messageId === messageId);
  const previous = index > 0 ? turns[index - 1] : undefined;
  const next = index >= 0 ? turns[index + 1] : undefined;
  const refreshing = session.isFetching || diagnostics.isFetching;
  const refresh = () => {
    if (refreshing) return;
    void session.refetch();
    void diagnostics.refetch();
  };

  return (
    <div className="flex flex-col">
      <div
        role="group"
        aria-label={t("chat_debug_turn_navigation")}
        className="border-ax-border flex items-center justify-between gap-2 border-b pb-3"
      >
        <span className="text-sm font-medium tabular-nums">
          {index >= 0
            ? t("chat_debug_turn_position", { number: index + 1, count: turns.length })
            : t("chat_debug_select_turn")}
        </span>
        <span className="flex shrink-0 items-center gap-0.5">
          <IconButton
            label={t("chat_debug_previous_turn")}
            icon={<ChevronUp className="size-4" />}
            variant="ghost"
            size="sm"
            isDisabled={!previous}
            onClick={() => previous && onSelectTurn(previous.messageId)}
          />
          <IconButton
            label={t("chat_debug_next_turn")}
            icon={<ChevronDown className="size-4" />}
            variant="ghost"
            size="sm"
            isDisabled={!next}
            onClick={() => next && onSelectTurn(next.messageId)}
          />
          <IconButton
            label={t("chat_debug_refresh")}
            icon={<RotateCcw className="size-4" />}
            variant="ghost"
            size="sm"
            isLoading={refreshing}
            onClick={refresh}
          />
        </span>
      </div>
      <QueryStateBoundary
        queries={[session, diagnostics]}
        rows={3}
        loadingLabel={t("chat_debug_loading")}
      >
        {() => {
          const message = session.data?.messages.find((candidate) => candidate.id === messageId);
          if (!message || !diagnostics.data) {
            // The answer streamed, but its turn is not in the saved
            // conversation yet (the backend persists it in the background).
            return (
              <div className="py-3">
                <Banner
                  status="info"
                  title={t("chat_debug_live_turn_title")}
                  description={t("chat_debug_live_turn_description")}
                  endContent={
                    <Button
                      size="sm"
                      label={t("chat_debug_retry")}
                      icon={<RotateCcw aria-hidden="true" />}
                      isLoading={refreshing}
                      isInterruptible
                      onClick={refresh}
                    />
                  }
                />
              </div>
            );
          }
          return <TurnDiagnostics message={message} diagnostics={diagnostics.data} />;
        }}
      </QueryStateBoundary>
    </div>
  );
}
