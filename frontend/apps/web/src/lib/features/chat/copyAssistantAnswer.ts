import { marked } from "marked";

import type { Settings } from "@eneo/eneo-js";

export type AssistantCopyFormat = "markdown" | "richtext";

const DEFAULT_COPY_FORMAT: AssistantCopyFormat = "markdown";
const COPY_FORMAT_SETTING_KEY = "preferred_text_format";

function sanitizeMarkdownForHtml(markdown: string): string {
  return markdown.replace(/<inref\s+id="[^"]+"(?:\s*\/?>|\s*><\/inref>)/g, "");
}

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

function getSanitizedRichTextHtml(markdown: string): string {
  const rendered = marked.parse(sanitizeMarkdownForHtml(markdown), {
    gfm: true,
    breaks: true
  }) as string;
  return sanitizeHtml(rendered);
}

function getPlainTextFromHtml(html: string): string {
  const container = document.createElement("div");
  container.innerHTML = html;
  return container.innerText.trim();
}

export function getPreferredAssistantCopyFormat(
  settings?: Pick<Settings, "chatbot_widget"> | null
): AssistantCopyFormat {
  const preferred = settings?.chatbot_widget?.[COPY_FORMAT_SETTING_KEY];
  return preferred === "richtext" || preferred === "markdown" ? preferred : DEFAULT_COPY_FORMAT;
}

export function setPreferredAssistantCopyFormat(
  settings: Pick<Settings, "chatbot_widget">,
  format: AssistantCopyFormat
) {
  return {
    ...(settings.chatbot_widget ?? {}),
    [COPY_FORMAT_SETTING_KEY]: format
  };
}

export async function copyAssistantAnswer(answer: string, format: AssistantCopyFormat) {
  if (format === "markdown") {
    await navigator.clipboard.writeText(answer);
    return;
  }

  const html = getSanitizedRichTextHtml(answer);
  const plainText = getPlainTextFromHtml(html);

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
