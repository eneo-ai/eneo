import { IntricError } from "@intric/intric-js";

export type TemplateFillErrorMessages = {
  missingFileContent: string;
  fallback: string;
};

function isMissingTemplateContentMessage(message: string): boolean {
  const normalized = message.toLowerCase();
  return (
    normalized.includes("selected template file has no binary content") ||
    normalized.includes("published docx template file has no binary content") ||
    normalized.includes("file content is missing")
  );
}

export function getTemplateFillErrorMessage(
  error: unknown,
  messages: TemplateFillErrorMessages
): string {
  if (error instanceof IntricError) {
    const readable = error.getReadableMessage();
    if (isMissingTemplateContentMessage(readable)) {
      return messages.missingFileContent;
    }
    return readable;
  }
  return messages.fallback;
}
