import { Banner } from "@astryxdesign/core/Banner";
import { useTranslations } from "use-intl";
import { EneoApiError } from "@/lib/api/errors";

type Named = { id: string; name: string };
type OwnConversation = { id: string; name: string | null; with: string | null };

/** What else uses the files of an assistant that could not be moved. */
export type MoveBlockers = {
  files: number;
  assistants: Named[];
  apps: Named[];
  services: Named[];
  /** The conversations of the person moving the assistant. */
  conversations: OwnConversation[];
  /** Conversations of other people: a number, nothing more is told. */
  otherConversations: number;
  /** Uses outside the space, which are not told either. */
  elsewhere: number;
};

function named(value: unknown): Named[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item: unknown) => {
    if (typeof item !== "object" || item === null) return [];
    const { id, name } = item as { id?: unknown; name?: unknown };
    return typeof id === "string" && typeof name === "string" ? [{ id, name }] : [];
  });
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * The blockers a refused move reports, or null for any other failure. Read
 * leniently: the server's list may grow, and a shape this does not know must
 * fall back to the ordinary error message, not break the dialog.
 */
export function moveBlockersOf(error: unknown): MoveBlockers | null {
  if (!(error instanceof EneoApiError) || error.reason !== "file_in_use_elsewhere") {
    return null;
  }
  const details = error.details;
  if (typeof details !== "object" || details === null) return null;
  const { files, blockers } = details as { files?: unknown; blockers?: unknown };
  if (typeof blockers !== "object" || blockers === null) return null;
  const found = blockers as Record<string, unknown>;
  const conversations = Array.isArray(found.conversations) ? found.conversations : [];
  return {
    files: typeof files === "number" ? files : 1,
    assistants: named(found.assistants),
    apps: named(found.apps),
    services: named(found.services),
    conversations: conversations.flatMap((item: unknown) => {
      if (typeof item !== "object" || item === null) return [];
      const one = item as { id?: unknown; name?: unknown; with?: unknown };
      return typeof one.id === "string"
        ? [{ id: one.id, name: text(one.name), with: text(one.with) }]
        : [];
    }),
    otherConversations:
      typeof found.other_conversations === "number" ? found.other_conversations : 0,
    elsewhere: typeof found.elsewhere === "number" ? found.elsewhere : 0
  };
}

/** Says why an assistant could not be moved, and what to remove first. */
export function MoveBlockersBanner({ blockers }: { blockers: MoveBlockers }) {
  const t = useTranslations();
  return (
    <Banner
      role="alert"
      status="error"
      title={t("move_blocked_title")}
      description={t("move_blocked_description", { count: blockers.files })}
      collapsible={false}
    >
      <ul className="flex list-disc flex-col gap-1 ps-5 text-sm">
        {blockers.assistants.map((assistant) => (
          <li key={`assistant-${assistant.id}`}>
            {t("move_blocked_assistant", { name: assistant.name })}
          </li>
        ))}
        {blockers.apps.map((app) => (
          <li key={`app-${app.id}`}>{t("move_blocked_app", { name: app.name })}</li>
        ))}
        {blockers.services.map((service) => (
          <li key={`service-${service.id}`}>{t("move_blocked_service", { name: service.name })}</li>
        ))}
        {blockers.conversations.map((conversation) => (
          <li key={`conversation-${conversation.id}`}>
            {conversation.with
              ? t("move_blocked_own_conversation_with", {
                  name: conversation.name ?? "",
                  with: conversation.with
                })
              : t("move_blocked_own_conversation", { name: conversation.name ?? "" })}
          </li>
        ))}
        {blockers.otherConversations > 0 && (
          <li>{t("move_blocked_other_conversations", { count: blockers.otherConversations })}</li>
        )}
        {blockers.elsewhere > 0 && (
          <li>{t("move_blocked_elsewhere", { count: blockers.elsewhere })}</li>
        )}
      </ul>
    </Banner>
  );
}
