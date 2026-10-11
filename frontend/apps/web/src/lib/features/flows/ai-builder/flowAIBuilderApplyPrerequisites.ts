import type { StepSpec, TargetKind } from "./protocol";
import { stepsTakeAudio } from "$lib/features/flows/flowRuntimeInputConfig";
import { hasAccessibleTranscriptionModel } from "$lib/features/spaces/spaceModelAvailability";
import type { TranscriptionModel } from "@eneo/eneo-js";

export type AIBuilderApplyBlockerCode = "transcription_model_required";

export type AIBuilderApplyBlocker = {
  code: AIBuilderApplyBlockerCode;
};

type TranscriptionModelAvailability = Pick<TranscriptionModel, "can_access">;

type PlanApplyPrerequisitesStep = Pick<StepSpec, "input_source" | "input_type" | "input_config">;

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
  // A flow that takes audio can be created without a transcription model
  // only where its author can then choose one: the space must have a usable
  // model, whether or not one is the organisation's default.
  const requiresTranscriptionModel =
    targetKind === "create" && stepsTakeAudio(plan?.proposal.spec.steps ?? []);

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
