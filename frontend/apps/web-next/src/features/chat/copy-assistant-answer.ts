import { marked } from "marked";
import { stripInrefs } from "@/lib/chat/inref";
import type { Schema } from "@/lib/api/models";

export type AssistantCopyFormat = "markdown" | "richtext";

const DEFAULT_COPY_FORMAT: AssistantCopyFormat = "markdown";
const COPY_FORMAT_SETTING_KEY = "preferred_text_format";

type SettingsWithChatWidget = Pick<Schema<"SettingsPublic">, "chatbot_widget">;
type ChatbotWidgetSettings = NonNullable<SettingsWithChatWidget["chatbot_widget"]>;

function sanitizeHtml(html: string): string {
  const template = document.createElement("template");
  template.innerHTML = html;

  template.content.querySelectorAll("script, style, iframe, object, embed").forEach((node) => {
    node.remove();
  });

  template.content.querySelectorAll("*").forEach((element) => {
    for (const attr of Array.from(element.attributes)) {
      const name = attr.name.toLowerCase();
      const value = attr.value.trim().toLowerCase();

      if (name.startsWith("on")) {
        element.removeAttribute(attr.name);
        continue;
      }

      if (
        (name === "href" || name === "src" || name === "xlink:href") &&
        value.startsWith("javascript:")
      ) {
        element.removeAttribute(attr.name);
      }
    }
  });

  return template.innerHTML;
}

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
  const markdown = stripInrefs(answer);
  const html = sanitizeHtml(
    marked.parse(markdown, {
      gfm: true,
      breaks: true
    }) as string
  );
  const container = document.createElement("div");
  container.innerHTML = html;
  return { html, plainText: (container.innerText || container.textContent || "").trim() };
}

export async function copyAssistantAnswer(
  answer: string,
  format: AssistantCopyFormat
): Promise<void> {
  if (format === "markdown") {
    await navigator.clipboard.writeText(stripInrefs(answer));
    return;
  }

  const { html, plainText } = assistantRichTextClipboardPayload(answer);

  if (typeof ClipboardItem !== "undefined" && navigator.clipboard.write) {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/plain": new Blob([plainText], { type: "text/plain" }),
        "text/html": new Blob([html], { type: "text/html" })
      })
    ]);
    return;
  }

  await navigator.clipboard.writeText(plainText);
}
