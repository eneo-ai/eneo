import { renderAnswerForClipboard } from "@/components/ai-elements/answer-markdown";
import { stripInrefs } from "@/lib/chat/inref";
import type { Schema } from "@/lib/api/models";

export type AssistantCopyFormat = "markdown" | "richtext";

const DEFAULT_COPY_FORMAT: AssistantCopyFormat = "markdown";
const COPY_FORMAT_SETTING_KEY = "preferred_text_format";

type SettingsWithChatWidget = Pick<Schema<"SettingsPublic">, "chatbot_widget">;
type ChatbotWidgetSettings = NonNullable<SettingsWithChatWidget["chatbot_widget"]>;

export function getPreferredAssistantCopyFormat(
  settings?: SettingsWithChatWidget | null
): AssistantCopyFormat {
  const preferred = settings?.chatbot_widget?.[COPY_FORMAT_SETTING_KEY];
  return preferred === "richtext" || preferred === "markdown" ? preferred : DEFAULT_COPY_FORMAT;
}

export function setPreferredAssistantCopyFormat(
  settings: SettingsWithChatWidget,
  format: AssistantCopyFormat
): ChatbotWidgetSettings {
  return {
    ...(settings.chatbot_widget ?? {}),
    [COPY_FORMAT_SETTING_KEY]: format
  };
}

export function assistantRichTextClipboardPayload(answer: string): {
  html: string;
  plainText: string;
} {
  return renderAnswerForClipboard(stripInrefs(answer));
}

/**
 * What copying an answer puts on the clipboard: the markdown as plain text,
 * or rich text as HTML with a plain-text twin.
 */
export function assistantClipboardContent(
  answer: string,
  format: AssistantCopyFormat
): { text: string; html: string | null } {
  if (format === "markdown") return { text: stripInrefs(answer), html: null };
  const { html, plainText } = assistantRichTextClipboardPayload(answer);
  return { text: plainText, html };
}

/** Whether the browser can put HTML on the clipboard. */
export function canCopyRichText(): boolean {
  return typeof ClipboardItem !== "undefined" && typeof navigator.clipboard?.write === "function";
}

/**
 * Puts HTML and its plain-text twin on the clipboard; resolves false when the
 * browser refuses. Astryx useClipboard writes text/plain only, so rich text
 * needs its own ClipboardItem write.
 */
export async function copyRichText({
  text,
  html
}: {
  text: string;
  html: string;
}): Promise<boolean> {
  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/plain": new Blob([text], { type: "text/plain" }),
        "text/html": new Blob([html], { type: "text/html" })
      })
    ]);
    return true;
  } catch {
    return false;
  }
}
