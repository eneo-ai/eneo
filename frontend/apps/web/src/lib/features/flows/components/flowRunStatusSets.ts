import { FLOW_RUN_STATUS_CAPABILITIES, FLOW_RUN_STATUS_FILTER_ORDER } from "@eneo/eneo-js";
import type { FlowRun, FlowRunStatusCapability } from "@eneo/eneo-js";

export type FlowRunStatus = FlowRun["status"];
export type FlowRunStatusFilter = FlowRunStatus | null;

type AssertNever<T extends never> = T;
type CapabilityStatus = (typeof FLOW_RUN_STATUS_CAPABILITIES)[number]["status"];

export const FLOW_RUN_STATUS_VALUES = FLOW_RUN_STATUS_CAPABILITIES.map(
  (capability) => capability.status
);

export type FlowRunStatusCoverageCheck = AssertNever<Exclude<FlowRunStatus, CapabilityStatus>>;

export const FLOW_RUN_STATUS_FILTER_OPTIONS = FLOW_RUN_STATUS_FILTER_ORDER;

export type FlowRunStatusFilterCoverageCheck = AssertNever<
  Exclude<FlowRunStatus, (typeof FLOW_RUN_STATUS_FILTER_OPTIONS)[number]>
>;

const FLOW_RUN_STATUS_CAPABILITY_BY_STATUS = new Map<string, FlowRunStatusCapability>(
  FLOW_RUN_STATUS_CAPABILITIES.map((capability) => [capability.status, capability])
);

function getFlowRunStatusCapability(status: string): FlowRunStatusCapability | undefined {
  return FLOW_RUN_STATUS_CAPABILITY_BY_STATUS.get(status);
}

export function isFlowRunActive(status: string): boolean {
  return getFlowRunStatusCapability(status)?.is_active ?? false;
}

export function shouldPollFlowRunStatus(status: string): boolean {
  return getFlowRunStatusCapability(status)?.should_poll ?? false;
}

export function isFlowRunTerminal(status: string): boolean {
  return getFlowRunStatusCapability(status)?.is_terminal ?? false;
}

export function isFlowRunCancellable(status: string): boolean {
  return getFlowRunStatusCapability(status)?.is_cancellable ?? false;
}

export function isFlowRunAwaitingReview(status: string): boolean {
  return getFlowRunStatusCapability(status)?.is_awaiting_review ?? false;
}

export function canRedispatchFlowRun(status: string): boolean {
  return getFlowRunStatusCapability(status)?.can_request_redispatch ?? false;
}
