import { m } from "$lib/paraglide/messages";
import type { AIBuilderFlowReviewFact, AIBuilderFlowReviewStep } from "./protocol";

/** The user-facing reading of one fact: a short title and the evidence line. */
export function describeReviewFact(
  fact: AIBuilderFlowReviewFact,
  steps: AIBuilderFlowReviewStep[]
): { title: string; evidence: string } {
  const described = describe(fact, steps);
  // Step labels read mid-sentence ("steg 2"); a card title starts a sentence.
  return {
    ...described,
    title: described.title.charAt(0).toUpperCase() + described.title.slice(1)
  };
}

function describe(
  fact: AIBuilderFlowReviewFact,
  steps: AIBuilderFlowReviewStep[]
): { title: string; evidence: string } {
  const stepLabel = (stepId: string): string => {
    const step = steps.find((candidate) => candidate.step_id === stepId);
    if (!step) return m.ai_builder_review_unknown_step();
    return step.label
      ? m.ai_builder_review_step_labelled({ number: String(step.step_order), label: step.label })
      : m.ai_builder_review_step({ number: String(step.step_order) });
  };
  switch (fact.kind) {
    case "output_not_observed_consumed":
      return {
        title: m.ai_builder_review_unconsumed_title({ step: stepLabel(fact.step_id) }),
        evidence: m.ai_builder_review_unconsumed_evidence({ runs: String(fact.run_count) })
      };
    case "repeated_error_code":
      return {
        title: m.ai_builder_review_repeated_error_title({ step: stepLabel(fact.step_id) }),
        evidence: m.ai_builder_review_repeated_error_evidence({
          code: fact.error_code,
          runs: String(fact.run_count)
        })
      };
    case "token_share":
      return {
        title: m.ai_builder_review_token_share_title({
          step: stepLabel(fact.step_id),
          percent: String(Math.round(fact.share * 100))
        }),
        evidence: m.ai_builder_review_share_evidence({ runs: String(fact.run_count) })
      };
    case "latency_share":
      return {
        title: m.ai_builder_review_latency_share_title({
          step: stepLabel(fact.step_id),
          percent: String(Math.round(fact.share * 100))
        }),
        evidence: m.ai_builder_review_share_evidence({ runs: String(fact.run_count) })
      };
    case "evidence_completeness":
      return {
        title: m.ai_builder_review_completeness({
          complete: String(fact.runs_with_all_step_results),
          incomplete: String(fact.runs_missing_step_results)
        }),
        evidence: ""
      };
  }
}

// Finding ids are stable for a published version, so a hidden finding stays
// hidden across reloads without the server keeping a preference; a republish
// changes every id and brings everything back, which is the right reset.
const STORAGE_PREFIX = "eneo.flow-review.hidden.";

export function dismissedFindingIds(flowId: string): Set<string> {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_PREFIX + flowId);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : []);
  } catch {
    return new Set();
  }
}

/** Remember one hidden finding, or forget them all when `findingId` is null. */
export function rememberDismissedFinding(flowId: string, findingId: string | null): void {
  try {
    const key = STORAGE_PREFIX + flowId;
    if (findingId === null) {
      globalThis.localStorage?.removeItem(key);
      return;
    }
    const next = dismissedFindingIds(flowId);
    next.add(findingId);
    globalThis.localStorage?.setItem(key, JSON.stringify([...next]));
  } catch {
    // Storage may be unavailable; hiding then lasts for this view only.
  }
}
