// Generated from backend/src/intric/flows/enums.py. Do not edit by hand.
const capabilities = [
  {
    status: "queued",
    is_active: true,
    should_poll: true,
    is_terminal: false,
    is_cancellable: true,
    is_awaiting_review: false,
    can_request_redispatch: true
  },
  {
    status: "running",
    is_active: true,
    should_poll: true,
    is_terminal: false,
    is_cancellable: true,
    is_awaiting_review: false,
    can_request_redispatch: false
  },
  {
    status: "awaiting_review",
    is_active: false,
    should_poll: true,
    is_terminal: false,
    is_cancellable: true,
    is_awaiting_review: true,
    can_request_redispatch: false
  },
  {
    status: "completed",
    is_active: false,
    should_poll: false,
    is_terminal: true,
    is_cancellable: false,
    is_awaiting_review: false,
    can_request_redispatch: false
  },
  {
    status: "failed",
    is_active: false,
    should_poll: false,
    is_terminal: true,
    is_cancellable: false,
    is_awaiting_review: false,
    can_request_redispatch: false
  },
  {
    status: "cancelled",
    is_active: false,
    should_poll: false,
    is_terminal: true,
    is_cancellable: false,
    is_awaiting_review: false,
    can_request_redispatch: false
  }
];

export const FLOW_RUN_STATUS_CAPABILITIES = Object.freeze(
  capabilities.map((capability) => Object.freeze(capability))
);
export const FLOW_RUN_STATUS_FILTER_ORDER = Object.freeze([
  "completed",
  "failed",
  "running",
  "queued",
  "awaiting_review",
  "cancelled"
]);
