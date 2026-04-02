export type AIBuilderApplyNavigation = {
  activeTab: "builder";
  builderStage: 1 | 4;
  focusStepIndex: number | null;
};

export function resolveAIBuilderApplyNavigation({
  stepCount,
  requestedFocusStepIndex
}: {
  stepCount: number;
  requestedFocusStepIndex: number | null | undefined;
}): AIBuilderApplyNavigation {
  if (stepCount <= 0) {
    return {
      activeTab: "builder",
      builderStage: 1,
      focusStepIndex: null
    };
  }

  const normalizedFocusIndex =
    typeof requestedFocusStepIndex === "number" &&
    Number.isInteger(requestedFocusStepIndex) &&
    requestedFocusStepIndex >= 0 &&
    requestedFocusStepIndex < stepCount
      ? requestedFocusStepIndex
      : 0;

  return {
    activeTab: "builder",
    builderStage: 4,
    focusStepIndex: normalizedFocusIndex
  };
}

export function resolveApplyFocusedStepId<T extends { id?: string | null }>(
  steps: T[] | null | undefined,
  focusStepIndex: number | null | undefined
): string | null {
  if (!steps?.length) {
    return null;
  }
  if (
    typeof focusStepIndex === "number" &&
    Number.isInteger(focusStepIndex) &&
    focusStepIndex >= 0 &&
    focusStepIndex < steps.length
  ) {
    return steps[focusStepIndex]?.id ?? null;
  }
  return steps[0]?.id ?? null;
}
