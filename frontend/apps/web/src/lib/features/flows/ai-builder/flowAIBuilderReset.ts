import type { AIBuilderStatus, TargetKind } from "./protocol";

interface EditStartOverVisibilityInput {
  targetKind: TargetKind;
  hasSession: boolean;
  messageCount: number;
  hasPlan: boolean;
  isConflict: boolean;
  statusMessage: AIBuilderStatus | null;
  hasApplyError: boolean;
  hasApplyResult: boolean;
  isStreaming: boolean;
}

export function shouldShowEditStartOver(input: EditStartOverVisibilityInput): boolean {
  if (input.targetKind !== "edit" || !input.hasSession) {
    return false;
  }

  return (
    input.messageCount > 0 ||
    input.hasPlan ||
    input.isConflict ||
    input.statusMessage !== null ||
    input.hasApplyError ||
    input.hasApplyResult ||
    input.isStreaming
  );
}
