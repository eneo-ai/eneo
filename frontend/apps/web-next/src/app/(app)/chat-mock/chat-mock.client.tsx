"use client";

import { ChatMessageList } from "@astryxdesign/core/Chat";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { useState } from "react";
import { deriveActivity } from "@/features/chat/activity";
import { ActivityPanel, type ActivityTab } from "@/features/chat/activity-panel";
import type { TurnDurations } from "@/features/chat/activity-timings";
import { ChatHeader } from "@/features/chat/chat-header";
import { ChatMessage, PendingAnswer } from "@/features/chat/chat-message";
import { Composer } from "@/features/chat/composer";
import { useAttachments } from "@/features/chat/use-attachments";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";

export type MockSection = {
  label: string;
  entries: { message: EneoUIMessage; isStreaming?: boolean; showResponseLabel?: boolean }[];
};

const PARTNER: ChatPartner = {
  type: "assistant",
  id: "mock-assistant",
  name: "Upphandlingsassistenten",
  spaceName: "Upphandling",
  securityClassification: "Klass 2 · Intern",
  description: "Hjälper dig att granska upphandlingar mot LOU.",
  completionModel: { id: "m", name: "Claude Haiku 4.5", token_limit: 200_000 },
  knowledge: [
    { id: "kb-policy", name: "Upphandlingspolicy", kind: "collection" },
    { id: "kb-lou", name: "LOU-vägledning", kind: "website" }
  ]
};

// Client-measured durations only exist for live turns; fake them for the preview.
const DURATIONS: Record<string, TurnDurations> = {
  "a-worst": {
    totalMs: 14_600,
    stepMs: {
      knowledge: 2_100,
      "reasoning-0": 1_200,
      "tool-call-1": 812,
      "tool-call-2": 1_400,
      "tool-call-3": 10_000,
      "tool-call-6": 600,
      answer: 5_900
    },
    tokens: 1_842,
    finishedAt: new Date(Date.UTC(2026, 8, 25, 7, 42)).toISOString()
  }
};

/** Dev-only preview of the real chat components with mock scenarios (see page.tsx). */
export function ChatMock({ sections }: { sections: MockSection[] }) {
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const [activity, setActivity] = useState<{
    messageId: string;
    tab: ActivityTab;
    source: number | null;
  } | null>({ messageId: "a-worst", tab: "steps", source: null });
  const [input, setInput] = useState("Föreslå en ny formulering av avsnitt 4.");
  const attachments = useAttachments(PARTNER);

  const messages = sections.flatMap((section) => section.entries);
  const selected = messages.find((entry) => entry.message.id === activity?.messageId);

  return (
    <div className="bg-ax-surface flex min-h-0 flex-1 flex-col">
      <ChatHeader
        partner={PARTNER}
        title="Upphandlingsanalys mot LOU"
        modelName="Claude Haiku 4.5"
        historyOpen={false}
        onToggleHistory={() => undefined}
        onNewConversation={() => undefined}
        menuItems={[{ label: "Byt namn", onClick: () => undefined }]}
      />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
          <ChatMessageList
            aria-label="Konversation"
            gap={6}
            className="mx-auto w-full max-w-[712px]"
          >
            {sections.map((section, sectionIndex) => (
              <div key={section.label} className="flex flex-col gap-6">
                {sectionIndex > 0 && (
                  <p className="text-ax-text-secondary text-center text-xs font-medium">
                    {section.label}
                  </p>
                )}
                {section.entries.map((entry) => (
                  <ChatMessage
                    key={entry.message.id}
                    message={entry.message}
                    assistant={PARTNER}
                    isStreaming={entry.isStreaming}
                    showResponseLabel={entry.showResponseLabel}
                    knowledge={PARTNER.knowledge}
                    durations={DURATIONS[entry.message.id] ?? null}
                    activityExpanded={activity?.messageId === entry.message.id}
                    onActivityToggle={(_trigger, request) =>
                      setActivity((current) =>
                        current?.messageId === entry.message.id && !request?.tab
                          ? null
                          : {
                              messageId: entry.message.id,
                              tab: request?.tab ?? "steps",
                              source: request?.source ?? null
                            }
                      )
                    }
                    feedback={
                      entry.message.id === "a-clean"
                        ? { value: 1, pending: false, onChange: () => undefined }
                        : null
                    }
                  />
                ))}
              </div>
            ))}
            <PendingAnswer assistant={PARTNER} />
          </ChatMessageList>
          <div className="bg-ax-surface sticky bottom-0 mx-auto w-full max-w-[712px] px-4 pb-3">
            <Composer
              value={input}
              onChange={setInput}
              onSubmit={() => undefined}
              canSubmit={input.trim().length > 0}
              busy={false}
              onStop={() => undefined}
              label="Meddelande till Upphandlingsassistenten"
              placeholder="Ställ en fråga…"
              attachments={attachments}
              onOpenFileDialog={() => undefined}
              capabilities={[
                { purpose: "web_search", available: true, reason: null },
                { purpose: "image_generation", available: false, reason: "no_active_provider" }
              ]}
              disabledCapabilities={new Set()}
              onToggleCapability={() => undefined}
              knowledge={PARTNER.knowledge}
            />
          </div>
        </div>
        {selected && activity && (
          <ActivityPanel
            variant={isDesktop ? "side" : "sheet"}
            messageId={selected.message.id}
            activity={deriveActivity(selected.message, {
              streaming: selected.isStreaming,
              knowledge: PARTNER.knowledge,
              tokens: DURATIONS[selected.message.id]?.tokens ?? null
            })}
            durations={DURATIONS[selected.message.id] ?? null}
            sessionId={null}
            tab={activity.tab}
            onTabChange={(tab) => setActivity({ ...activity, tab, source: null })}
            focusSource={activity.source}
            onClose={() => setActivity(null)}
          />
        )}
      </div>
    </div>
  );
}
