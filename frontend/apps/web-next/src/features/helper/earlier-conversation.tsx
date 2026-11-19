import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useEffect, useId, useMemo, useRef } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { mapSessionMessages } from "@/lib/chat/map-session";
import { ChatMessage } from "@/features/chat/chat-message";
import { questionAnsweredBy } from "@/features/chat/questions";
import type { HelperAdapter, HelperChat, HelperConversation } from "./helper-adapter";
import { useConversationTime } from "./helper-controls";

/**
 * An earlier conversation of the chat, read only, in the current one's
 * place. A bar says so, with when it was last active, and leads back to the
 * current conversation; it is no alert, and its heading takes the focus when
 * the conversation shows. The messages are drawn as the chat draws them, one
 * by one as other pages show a saved conversation: the target's cards and
 * references included, their buttons working as they do in the chat (a
 * proposal applied is the person's own change of the target, not a
 * message). There is no composer: nothing is asked in it again.
 */
export function EarlierConversation({
  chat,
  conversation,
  adapter,
  onBack
}: {
  chat: HelperChat;
  conversation: HelperConversation;
  adapter: HelperAdapter;
  onBack: () => void;
}) {
  const t = useTranslations();
  const timeOf = useConversationTime();
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const read = useQuery({
    queryKey: ["conversations", "detail", conversation.session_id],
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/conversations/{session_id}/", {
          params: { path: { session_id: conversation.session_id } },
          signal
        })
      ),
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: false
  });
  const messages = useMemo(
    () => (read.data ? mapSessionMessages(read.data.messages) : []),
    [read.data]
  );
  // The chat's assistant is hidden and named after its target; the panel
  // names it by what it does, as in the current conversation.
  const assistant = { id: chat.assistant_id, name: adapter.texts.partnerName, iconId: null };

  return (
    <section aria-labelledby={headingId} className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0 px-4 pt-3">
        <Banner
          status="info"
          collapsible={false}
          title={
            <Heading
              level={3}
              ref={heading}
              id={headingId}
              tabIndex={-1}
              weight="semibold"
              className="focus-visible:outline-ring rounded-ax-inner text-sm focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              {t("helper_earlier_heading")}
            </Heading>
          }
          description={t("helper_earlier_description", {
            time: timeOf(conversation.last_asked_at)
          })}
          endContent={<Button label={t("helper_earlier_back")} size="sm" onClick={onBack} />}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {read.isError ? (
          <ListError error={read.error} onRetry={() => void read.refetch()} />
        ) : read.data === undefined ? (
          <LoadingState label={t("helper_earlier_loading")} rows={3} />
        ) : (
          <div className="mx-auto flex w-full max-w-[712px] flex-col gap-6">
            {messages.map((message, index) => (
              <ChatMessage
                key={message.id}
                message={message}
                assistant={assistant}
                sessionId={conversation.session_id}
                references={adapter.references}
                toolCards={adapter.toolCards}
                answersQuestion={questionAnsweredBy(messages, index)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
