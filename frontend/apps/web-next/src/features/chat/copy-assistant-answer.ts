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

export async function assistantRichTextClipboardPayload(answer: string) {
  const { renderAnswerForClipboard } = await import("@/components/ai-elements/answer-clipboard");
  return renderAnswerForClipboard(stripInrefs(answer));
}

/**
 * What copying an answer puts on the clipboard: the markdown as plain text,
 * or rich text as a plain-text twin and HTML. Both rich-text representations
 * wait for the clipboard renderer; formulas also wait for KaTeX.
 */
export function assistantClipboardContent(
  answer: string,
  format: AssistantCopyFormat
): { text: string | Promise<string>; html: (() => Promise<string>) | null } {
  if (format === "markdown") return { text: stripInrefs(answer), html: null };
  const payload = assistantRichTextClipboardPayload(answer);
  return {
    text: payload.then(({ plainText }) => plainText),
    html: () => payload.then(({ html }) => html())
  };
}

/** Whether the browser can put HTML on the clipboard. */
export function canCopyRichText(): boolean {
  return typeof ClipboardItem !== "undefined" && typeof navigator.clipboard?.write === "function";
}

/**
 * Puts HTML and its plain-text twin on the clipboard; resolves false when the
 * browser refuses or the HTML cannot be made. Astryx useClipboard writes
 * text/plain only, so rich text needs its own ClipboardItem write. The write
 * starts at once, inside the click (Safari requires it), and both representations
 * follow as promises when the renderer is ready.
 */
export async function copyRichText({
  text,
  html
}: {
  text: string | Promise<string>;
  html: () => Promise<string>;
}): Promise<boolean> {
  try {
    const representations = {
      "text/plain": Promise.resolve(text).then(
        (value) => new Blob([value], { type: "text/plain" })
      ),
      "text/html": html().then((value) => new Blob([value], { type: "text/html" }))
    };
    await Promise.all([
      ...Object.values(representations),
      // The executor starts the write synchronously and captures constructor errors.
      // Observe the representations even if the browser refuses before reading them.
      new Promise<void>((resolve) =>
        resolve(navigator.clipboard.write([new ClipboardItem(representations)]))
      )
    ]);
    return true;
  } catch {
    return false;
  }
}
