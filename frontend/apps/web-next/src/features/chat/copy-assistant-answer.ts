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
  html: () => Promise<string>;
  plainText: string;
} {
  return renderAnswerForClipboard(stripInrefs(answer));
}

/**
 * What copying an answer puts on the clipboard: the markdown as plain text,
 * or rich text as a plain-text twin and HTML, rendered on demand (its formulas
 * wait for KaTeX).
 */
export function assistantClipboardContent(
  answer: string,
  format: AssistantCopyFormat
): { text: string; html: (() => Promise<string>) | null } {
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
 * browser refuses or the HTML cannot be made. Astryx useClipboard writes
 * text/plain only, so rich text needs its own ClipboardItem write. The write
 * starts at once, inside the click (Safari requires it), and the HTML follows
 * as a promise when it is ready.
 */
export async function copyRichText({
  text,
  html
}: {
  text: string;
  html: () => Promise<string>;
}): Promise<boolean> {
  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/plain": new Blob([text], { type: "text/plain" }),
        "text/html": html().then((value) => new Blob([value], { type: "text/html" }))
      })
    ]);
    return true;
  } catch {
    return false;
  }
}
