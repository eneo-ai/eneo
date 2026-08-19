import type { StepSpec, TargetKind } from "./protocol";
import { hasAccessibleTranscriptionModel } from "$lib/features/spaces/spaceModelAvailability";
import type { TranscriptionModel } from "@eneo/eneo-js";

export type AIBuilderApplyBlockerCode = "transcription_model_required";

export type AIBuilderApplyBlocker = {
  code: AIBuilderApplyBlockerCode;
};

type TranscriptionModelAvailability = Pick<TranscriptionModel, "can_access">;

type PlanApplyPrerequisitesStep = Pick<StepSpec, "input_source" | "input_type">;

type PlanApplyPrerequisitesPlan = {
  proposal: {
    spec: {
      steps: readonly PlanApplyPrerequisitesStep[];
    };
  };
};

type ApplyPrerequisitesInput = {
  plan: PlanApplyPrerequisitesPlan | null;
  targetKind: TargetKind | null | undefined;
  transcriptionModels: readonly TranscriptionModelAvailability[] | null | undefined;
};

export type AIBuilderApplyPrerequisites = {
  blockers: readonly AIBuilderApplyBlocker[];
  canApply: boolean;
};

export function getAIBuilderApplyPrerequisites({
  plan,
  targetKind,
  transcriptionModels
}: ApplyPrerequisitesInput): AIBuilderApplyPrerequisites {
  const requiresTranscriptionModel =
    targetKind === "create" &&
    (plan?.proposal.spec.steps.some(
      (step) => step.input_source === "flow_input" && step.input_type === "audio"
    ) ??
      false);

  const blockers: AIBuilderApplyBlocker[] =
    requiresTranscriptionModel && !hasAccessibleTranscriptionModel(transcriptionModels)
      ? [
          {
            code: "transcription_model_required"
          }
        ]
      : [];

  return {
    blockers,
    canApply: blockers.length === 0
  };
}

export function hasAIBuilderApplyBlocker(
  prerequisites: AIBuilderApplyPrerequisites,
  code: AIBuilderApplyBlockerCode
): boolean {
  return prerequisites.blockers.some((blocker) => blocker.code === code);
}
