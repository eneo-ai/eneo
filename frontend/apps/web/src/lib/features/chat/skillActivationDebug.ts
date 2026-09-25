import type { components } from "@eneo/eneo-js";

export type SkillActivationReference = components["schemas"]["SkillActivationReference"];
export type SkillActivationRejection = components["schemas"]["SkillActivationRejection"];
export type SkillActivationEvidence = components["schemas"]["SkillActivationEvidenceV1"];

export type SkillActivationOutcome = "accepted" | "repeated" | "blocked" | "rejected";

export type SkillActivationDebugRow = SkillActivationReference & {
  activationKey: string;
  candidateState: "available" | "blocked";
  activationMode: "always" | "on_demand" | null;
  outcomes: SkillActivationOutcome[];
  rejectionReasons: SkillActivationRejection["reason"][];
};

export function buildSkillActivationRows(
  evidence: SkillActivationEvidence
): SkillActivationDebugRow[] {
  const initiallyActive = new Set(evidence.initially_active);
  const accepted = new Set(evidence.accepted ?? []);
  const repeated = new Set(evidence.repeated ?? []);
  const blocked = new Set(
    evidence.blocked.map((reference) => reference.activation_key ?? reference.skill_revision_id)
  );
  const rejectionReasons = new Map<string, SkillActivationRejection["reason"][]>();
  for (const rejection of evidence.rejected ?? []) {
    const reasons = rejectionReasons.get(rejection.activation_key) ?? [];
    reasons.push(rejection.reason);
    rejectionReasons.set(rejection.activation_key, reasons);
  }

  return [
    ...evidence.available.map((reference) => ({ reference, candidateState: "available" as const })),
    ...evidence.blocked.map((reference) => ({ reference, candidateState: "blocked" as const }))
  ]
    .sort((left, right) => left.reference.position - right.reference.position)
    .map(({ reference, candidateState }) => {
      const activationKey = reference.activation_key ?? reference.skill_revision_id;
      const outcomes: SkillActivationOutcome[] = [];
      if (accepted.has(activationKey)) outcomes.push("accepted");
      if (repeated.has(activationKey)) outcomes.push("repeated");
      if (blocked.has(activationKey)) outcomes.push("blocked");
      if (rejectionReasons.has(activationKey)) outcomes.push("rejected");

      return {
        ...reference,
        activationKey,
        candidateState,
        activationMode:
          candidateState === "blocked"
            ? null
            : initiallyActive.has(activationKey)
              ? "always"
              : "on_demand",
        outcomes,
        rejectionReasons: rejectionReasons.get(activationKey) ?? []
      };
    });
}

export function summarizeSkillActivation(evidence: SkillActivationEvidence) {
  const enteredContext = new Set([...evidence.initially_active, ...(evidence.accepted ?? [])]);
  return {
    available: evidence.available.length,
    enteredContext: enteredContext.size,
    blocked: evidence.blocked.length,
    rejected: evidence.rejected?.length ?? 0
  };
}

export function getUnmatchedActivationRejections(evidence: SkillActivationEvidence) {
  const knownKeys = new Set(
    [...evidence.available, ...evidence.blocked].map(
      (reference) => reference.activation_key ?? reference.skill_revision_id
    )
  );
  return (evidence.rejected ?? []).filter((rejection) => !knownKeys.has(rejection.activation_key));
}
