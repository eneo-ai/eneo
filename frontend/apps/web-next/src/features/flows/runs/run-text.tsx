"use client";

import { MessageResponse } from "@/components/ai-elements/message";

/**
 * Text a step or the run produced, as Markdown through the chat's renderer
 * (GFM tables and lists, sanitizing, code and math). A line break inside a
 * paragraph stays a line break: step output (a transcript, a plain answer)
 * is often written line by line, and Markdown would join those lines.
 */
export function RunText({ text }: { text: string }) {
  return (
    <MessageResponse className="text-ax-text text-sm leading-relaxed [&_p]:whitespace-pre-line">
      {text}
    </MessageResponse>
  );
}
