type PromptShape =
  | {
      text?: string | null;
      description?: string | null;
    }
  | null
  | undefined;

export function buildNextFlowPrompt(
  prompt: PromptShape,
  text: string
): { text: string; description: string } {
  return {
    text,
    description: typeof prompt?.description === "string" ? prompt.description : ""
  };
}
