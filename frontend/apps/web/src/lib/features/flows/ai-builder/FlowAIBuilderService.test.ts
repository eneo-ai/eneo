import { describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import { FlowAIBuilderService } from "./FlowAIBuilderService.svelte.ts";
import type {
  AIBuilderDraftSession,
  AIBuilderError,
  AIBuilderModel,
  AIBuilderSession,
  ApplyError,
  ApplyResult,
  ChatMessage,
  ProposedPlan
} from "./protocol";

function makeSession(overrides: Partial<AIBuilderSession> = {}): AIBuilderSession {
  return {
    session_id: "session-1",
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: null,
    conversation: [],
    ...overrides
  };
}

function makeDraft(overrides: Partial<AIBuilderDraftSession> = {}): AIBuilderDraftSession {
  return {
    session_id: "draft-1",
    space_id: "space-1",
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: null,
    draft_title: "Recovered draft",
    created_at: "2026-03-15T10:00:00Z",
    updated_at: "2026-03-15T10:05:00Z",
    ...overrides
  };
}

function makePlan(overrides: Partial<ProposedPlan> = {}): ProposedPlan {
  return {
    plan_id: "plan-1",
    status: "proposed",
    proposal: {
      spec: {
        flow_name: "Flow",
        flow_description: "",
        steps: [],
        form_fields: null
      },
      assumptions: [],
      lint_warnings: [],
      execution_shape: {
        completion_model_step_count: 0,
        transcription_model_step_count: 0,
        deterministic_step_count: 0,
        schema_constrained_step_count: 0,
        mapped_step_upper_bounds: []
      }
    },
    ...overrides
  };
}

function makeAIBuilderError(overrides: Partial<AIBuilderError> = {}): AIBuilderError {
  return {
    schema_version: 2,
    code: "invalid_existing_step_ref",
    category: "bad_request",
    message: "Plan changed",
    phase: "router",
    request_id: "req-test",
    eneo_error_code: 9007,
    diagnostic_context: null,
    details: {},
    ...overrides
  };
}

function makeService() {
  return new FlowAIBuilderService(
    {
      client: {
        fetch: vi.fn(),
        stream: vi.fn()
      }
    } as never,
    "space-1",
    null
  );
}

describe("FlowAIBuilderService", () => {
  it("owns and clears the saved-step launch scope", () => {
    const service = makeService();
    const scope = {
      editContext: { kind: "saved_flow_step" as const, flow_step_id: "step-1" },
      stepName: "Extract facts",
      stepNumber: 2
    };

    service.setSavedFlowStepScope(scope);
    expect(service.savedFlowStepScope).toEqual(scope);

    service.clearSavedFlowStepScope();
    expect(service.savedFlowStepScope).toBeNull();
  });

  it("keeps the saved-step scope when a fresh session is skipped and drops it once one exists", async () => {
    const session = {
      session_id: "s-2",
      space_id: "space-1",
      status: "chatting",
      target_kind: "edit",
      flow_id: "flow-1",
      latest_plan_id: null,
      conversation: [],
      latest_turn: null
    };
    const fetch = vi.fn(async () => session);
    const service = new FlowAIBuilderService(
      { client: { fetch, stream: vi.fn() } } as never,
      "space-1",
      "flow-1"
    );
    const scope = {
      editContext: { kind: "saved_flow_step" as const, flow_step_id: "step-1" },
      stepName: "Extract facts",
      stepNumber: 2
    };
    service.setSavedFlowStepScope(scope);

    service.seedState({ pendingOperation: { kind: "applying", planId: "p-1" } as never });
    expect(await service.startFreshSession("edit")).toBe(false);
    expect(service.savedFlowStepScope).toEqual(scope);
    expect(fetch).not.toHaveBeenCalled();

    service.seedState({ pendingOperation: null });
    expect(await service.startFreshSession("edit")).toBe(true);
    expect(service.savedFlowStepScope).toBeNull();
  });

  it("does not lend the saved-step scope to the session that replaced it", () => {
    const service = makeService();
    const scope = {
      editContext: { kind: "saved_flow_step" as const, flow_step_id: "step-1" },
      stepName: "Extract facts",
      stepNumber: 2
    };
    const session = (sessionId: string) => ({
      session_id: sessionId,
      space_id: "space-1",
      status: "chatting",
      target_kind: "edit",
      flow_id: "flow-1",
      latest_plan_id: null,
      conversation: [],
      latest_turn: null
    });

    service.seedState({ session: session("s-ongoing") as never });
    service.setSavedFlowStepScope(scope);
    expect(service.activeStepTransportContext).toEqual(scope.editContext);

    // The step a replacement session must not inherit is this one.
    service.seedState({ session: session("s-fresh") as never });
    expect(service.savedFlowStepScope).toBeNull();
    expect(service.activeStepTransportContext).toBeNull();

    // A refused replacement puts the session back, and its step with it.
    service.seedState({ session: session("s-ongoing") as never });
    expect(service.activeStepTransportContext).toEqual(scope.editContext);
  });

  it("shows the editor's launch until a turn is delivered, then the server's projection", async () => {
    const projected = {
      context: {
        kind: "proposed_plan" as const,
        plan_id: "plan-1",
        scope: "step" as const,
        target_existing_step_ref: "existing_step_2",
        target_plan_step_ref: "step_2",
        target_step_name: "Extract facts",
        target_step_number: 2
      },
      step_number: 2,
      step_name: "Extract facts",
      preserves_output_contract: false
    };
    const stream = vi.fn(async (_path, _init, handlers) => {
      handlers.onMessage?.({ id: "", event: "done", data: "" }, new AbortController());
      handlers.onClose?.();
    });
    // The read-back after the delivered turn carries the accepted user turn.
    const fetch = vi.fn(async () =>
      makeSession({
        session_id: "s-1",
        conversation: [
          {
            message_id: "u1",
            role: "user",
            content: "tydligare",
            timestamp: "2026-07-11T09:00:00Z"
          }
        ],
        edit_scope: projected
      })
    );
    const service = new FlowAIBuilderService(
      { client: { fetch, stream } } as never,
      "space-1",
      "flow-1"
    );
    service.seedState({
      session: makeSession({ session_id: "s-1" }),
      availableModels: [
        { id: "model-low", name: "Low", provider: "openai", availability: { state: "ready" } }
      ],
      defaultModelId: "model-low",
      modelLoadStatus: "loaded"
    });
    const launch = {
      editContext: { kind: "saved_flow_step" as const, flow_step_id: "step-1" },
      stepName: "Extract facts",
      stepNumber: 2
    };
    service.setSavedFlowStepScope(launch);
    expect(service.activeStepTransportContext).toEqual(launch.editContext);

    expect(await service.sendMessage("tydligare", undefined, undefined, launch.editContext)).toBe(
      "delivered"
    );

    // The scoped turn was read back from the server: the launch is spent and
    // the projection names the step on the plan the turn produced.
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}",
      expect.objectContaining({ method: "get" })
    );
    expect(service.savedFlowStepScope).toBeNull();
    expect(service.activeStepScope).toEqual({ stepName: "Extract facts", stepNumber: 2 });
    expect(service.activeStepTransportContext).toEqual(projected.context);
    expect(service.activeStepScopeLocked).toBe(false);
  });

  it("keeps the editor's launch through a refused send and a plain re-read, and retires it with the accepted turn", async () => {
    const same = makeSession({ session_id: "s-1" });
    let deliver = false;
    const fetch = vi.fn(async () =>
      deliver
        ? makeSession({
            session_id: "s-1",
            latest_plan_id: "plan-1",
            conversation: [
              {
                message_id: "u1",
                role: "user",
                content: "tydligare",
                timestamp: "2026-07-11T09:00:00Z"
              }
            ],
            edit_scope: {
              context: {
                kind: "proposed_plan",
                plan_id: "plan-1",
                scope: "step",
                target_existing_step_ref: "existing_step_2",
                target_plan_step_ref: "step_2"
              },
              step_number: 2,
              step_name: "Extract facts",
              preserves_output_contract: false
            }
          })
        : same
    );
    let fail = true;
    const stream = vi.fn(async (_path, _init, handlers) => {
      if (fail) throw new Error("transport down");
      handlers.onMessage?.({ id: "", event: "done", data: "" }, new AbortController());
      handlers.onClose?.();
    });
    const service = new FlowAIBuilderService(
      { client: { fetch, stream } } as never,
      "space-1",
      "flow-1"
    );
    service.seedState({
      session: same,
      availableModels: [
        { id: "model-low", name: "Low", provider: "openai", availability: { state: "ready" } }
      ],
      defaultModelId: "model-low",
      modelLoadStatus: "loaded"
    });
    const launch = {
      editContext: { kind: "saved_flow_step" as const, flow_step_id: "step-1" },
      stepName: "Extract facts",
      stepNumber: 2
    };
    service.setSavedFlowStepScope(launch);

    // The send never reached the server: the read-back returns the same
    // session and the selected step stays selected for the resubmission.
    expect(
      await service.sendMessage("tydligare", undefined, undefined, launch.editContext)
    ).not.toBe("delivered");
    await service.refreshSession();
    expect(service.activeStepTransportContext).toEqual(launch.editContext);

    // The accepted turn supersedes it: the server's projection owns the scope.
    fail = false;
    deliver = true;
    expect(await service.sendMessage("tydligare", undefined, undefined, launch.editContext)).toBe(
      "delivered"
    );
    expect(service.savedFlowStepScope).toBeNull();
    expect(service.activeStepTransportContext).toMatchObject({
      kind: "proposed_plan",
      plan_id: "plan-1"
    });
  });

  it("restores scoped plan transport after a page reload without browser-only scope", () => {
    const service = makeService();
    service.seedState({
      session: makeSession({
        session_id: "s-1",
        edit_scope: {
          context: {
            kind: "proposed_plan",
            plan_id: "plan-1",
            scope: "step",
            target_existing_step_ref: "existing_step_2",
            target_plan_step_ref: "step_2",
            target_step_name: "Selected",
            target_step_number: 2
          },
          step_number: 2,
          step_name: "Selected",
          preserves_output_contract: false
        }
      })
    });

    expect(service.activeStepScope).toEqual({ stepName: "Selected", stepNumber: 2 });
    expect(service.activeStepTransportContext).toMatchObject({
      kind: "proposed_plan",
      plan_id: "plan-1",
      target_existing_step_ref: "existing_step_2"
    });
  });

  it("restores a saved-step scope before any proposal exists, and a repair's locked scope", () => {
    const service = makeService();
    const context = { kind: "saved_flow_step" as const, flow_step_id: "step-2" };
    service.seedState({
      session: makeSession({
        session_id: "s-1",
        edit_scope: {
          context,
          step_number: 2,
          step_name: "Strukturera",
          preserves_output_contract: true
        }
      })
    });

    expect(service.activeStepScope).toEqual({ stepName: "Strukturera", stepNumber: 2 });
    expect(service.activeStepTransportContext).toEqual(context);
    // A repair keeps the failed step's contract whatever the composer shows.
    expect(service.activeStepScopeLocked).toBe(true);
    service.clearActiveStepScope();
    expect(service.activeStepScope).toEqual({ stepName: "Strukturera", stepNumber: 2 });
  });

  it("names a projected step without a name after the flow's fallback", () => {
    const service = makeService();
    service.seedState({
      session: makeSession({
        session_id: "s-1",
        edit_scope: {
          context: { kind: "saved_flow_step", flow_step_id: "step-3" },
          step_number: 3,
          step_name: null,
          preserves_output_contract: false
        }
      })
    });
    expect(service.activeStepScope).toEqual({
      stepName: m.flow_step_unnamed(),
      stepNumber: 3
    });
  });

  it("keeps a dismissed projection dismissed until a newer accepted turn projects another", () => {
    const service = makeService();
    const scopeOf = (ref: string, name: string) => ({
      context: {
        kind: "proposed_plan" as const,
        plan_id: "plan-1",
        scope: "step" as const,
        target_existing_step_ref: ref,
        target_plan_step_ref: null,
        target_step_name: name,
        target_step_number: 2
      },
      step_number: 2,
      step_name: name,
      preserves_output_contract: false
    });
    service.seedState({
      session: makeSession({ session_id: "s-1", edit_scope: scopeOf("existing_step_2", "Två") })
    });
    expect(service.activeStepScope).not.toBeNull();

    service.clearActiveStepScope();
    expect(service.activeStepScope).toBeNull();
    expect(service.activeStepTransportContext).toBeNull();

    // The same session re-read (no new accepted turn) stays dismissed.
    service.seedState({
      session: makeSession({ session_id: "s-1", edit_scope: scopeOf("existing_step_2", "Två") })
    });
    expect(service.activeStepScope).toBeNull();

    // An accepted turn supersedes the dismissal: the server's word again.
    service.seedState({
      session: makeSession({
        session_id: "s-1",
        conversation: [
          { message_id: "u1", role: "user", content: "x", timestamp: "2026-07-11T09:00:00Z" }
        ],
        edit_scope: scopeOf("existing_step_3", "Tre")
      })
    });
    expect(service.activeStepScope).toEqual({ stepName: "Tre", stepNumber: 2 });
  });

  it("passes Driver-owned field getters through the reactive facade", () => {
    const service = makeService();
    const session = makeSession({ session_id: "session-2", status: "awaiting_approval" });
    const messages: ChatMessage[] = [
      {
        role: "user",
        content: "Build a summary flow",
        timestamp: 10
      }
    ];
    const currentPlan = makePlan({ status: "approved" });
    const applyError: ApplyError = makeAIBuilderError();
    const error = makeAIBuilderError({
      code: "unknown",
      category: "internal",
      message: "Something failed",
      phase: "client",
      request_id: null,
      eneo_error_code: null
    });
    const applyResult: ApplyResult = {
      flow_id: "flow-1",
      flow_name: "Flow",
      steps_created: 1,
      steps_updated: 2,
      steps_removed: 0
    };
    const availableModels: AIBuilderModel[] = [
      {
        id: "model-1",
        name: "Model",
        provider: "openai",
        availability: { state: "ready" }
      }
    ];
    const draftSessions = [makeDraft({ session_id: "draft-2" })];

    service.seedState({
      session,
      messages,
      currentPlan,
      streamState: "streaming",
      isInitializing: true,
      error,
      applyError,
      applyResult,
      isConflict: true,
      statusMessage: "repairing",
      availableModels,
      draftSessions
    });

    expect(service.session).toBe(session);
    expect(service.messages).toBe(messages);
    expect(service.currentPlan).toBe(currentPlan);
    expect(service.isStreaming).toBe(true);
    expect(service.isInitializing).toBe(true);
    expect(service.error).toBe(error);
    expect(service.applyError).toBe(applyError);
    expect(service.applyResult).toBe(applyResult);
    expect(service.isConflict).toBe(true);
    expect(service.statusMessage).toBe("repairing");
    expect(service.availableModels).toBe(availableModels);
    expect(service.draftSessions).toBe(draftSessions);
    expect(service.sessionStatus).toBe("awaiting_approval");
  });

  it("exposes Driver-owned state through reactive facade getters", () => {
    const service = makeService();

    expect(service.session).toBeNull();
    expect(service.canSendMessage).toBe(false);

    service.seedState({
      session: makeSession({ status: "chatting" }),
      streamState: "idle"
    });

    expect(service.session?.session_id).toBe("session-1");
    // The planner model is the server's default; a slow or failed model-name
    // request must never block the first message.
    expect(service.canSendMessage).toBe(true);

    service.seedState({ streamState: "streaming" });

    expect(service.isStreaming).toBe(true);
    expect(service.canSendMessage).toBe(false);
  });

  it("delegates recoverable draft filtering to the Driver state owner", () => {
    const service = makeService();

    service.seedState({
      draftSessions: [
        makeDraft({ session_id: "recoverable" }),
        makeDraft({ session_id: "wrong-space", space_id: "space-2" }),
        makeDraft({ session_id: "applied", status: "applied" }),
        makeDraft({ session_id: "cancelled", status: "cancelled" }),
        makeDraft({ session_id: "edit", target_kind: "edit", flow_id: "flow-1" })
      ]
    });

    expect(service.recoverableCreateDrafts.map((draft) => draft.session_id)).toEqual([
      "recoverable"
    ]);
    expect(service.hasRecoverableCreateDraft).toBe(true);
  });

  it("updates derived phase from Driver-owned messages and plan state", () => {
    const service = makeService();

    expect(service.phase).toBe("discovering");

    service.seedState({
      messages: [
        {
          role: "assistant",
          content: "",
          requirementsSummary: {
            summary: "Build a flow",
            key_decisions: [],
            input_description: "Uploaded files",
            output_description: "Summary",
            requirements_version: "req-1"
          },
          timestamp: 1
        }
      ]
    });

    expect(service.phase).toBe("confirming");

    // A plan can only be reviewed against a confirmed disclosure; an
    // unconfirmed one keeps the builder in confirming even with a plan loaded.
    service.seedState({ currentPlan: makePlan() });
    expect(service.phase).toBe("confirming");

    service.seedState({
      messages: [
        ...service.messages,
        {
          role: "user",
          content: "",
          metadata: { requirements_confirmed: true, requirements_version: "req-1" },
          timestamp: 2
        }
      ]
    });

    expect(service.phase).toBe("reviewing");
  });

  describe("review lifetime", () => {
    function deferred<T>() {
      let resolve!: (value: T) => void;
      let reject!: (reason: unknown) => void;
      const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
      });
      return { promise, resolve, reject };
    }
    const packet = (version: number) => ({
      flow_version: version,
      definition_checksum: `sum-${version}`
    });
    const judged = (version: number) => ({
      flow_version: version,
      definition_checksum: `sum-${version}`,
      suggestions: []
    });
    function makeReviewService() {
      const fetch = vi.fn();
      const service = new FlowAIBuilderService(
        { client: { fetch, stream: vi.fn() } } as never,
        "space-1",
        "flow-1"
      );
      return { service, fetch };
    }
    /** A listed ready default, so the composer has a model a request can run. */
    function seedReadyModel(service: FlowAIBuilderService) {
      service.seedState({
        availableModels: [
          { id: "model-low", name: "Low", provider: "openai", availability: { state: "ready" } }
        ],
        defaultModelId: "model-low",
        modelLoadStatus: "loaded"
      });
    }

    it("drops a review packet that arrives after the review closed", async () => {
      const { service, fetch } = makeReviewService();
      // An active session with a listing; a review's packet would raise the
      // listing's floor, so a discarded packet must leave it untouched.
      const lowModel = {
        id: "model-low",
        name: "Low",
        provider: "openai",
        availability: { state: "ready" }
      };
      service.seedState({
        session: makeSession({ session_id: "s-review", flow_id: "flow-1" }),
        availableModels: [lowModel as never],
        defaultModelId: "model-low",
        modelLoadStatus: "loaded"
      });
      const pending = deferred<object>();
      fetch.mockReturnValueOnce(pending.promise);

      const opened = service.openReview();
      expect(service.review.status).toBe("loading");
      service.closeReview();
      pending.resolve({ ...packet(1), evidence_classification_level: 2 });
      await opened;

      expect(service.review).toEqual({ status: "closed" });
      // A discarded packet leaves no listing behind: the only request made
      // was the packet's own, and the conversation's list still stands.
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(service.effectiveModel?.id).toBe("model-low");
    });

    it("drops suggestions that answer a review that was reopened on another version", async () => {
      const { service, fetch } = makeReviewService();
      const pendingSuggestions = deferred<object>();
      fetch
        .mockResolvedValueOnce(packet(1))
        .mockReturnValueOnce(pendingSuggestions.promise)
        .mockResolvedValueOnce(packet(2));
      seedReadyModel(service);

      await service.openReview();
      const requested = service.requestSuggestions();
      await service.openReview();
      pendingSuggestions.resolve(judged(1));
      await requested;

      expect(service.review).toEqual({ status: "ready", packet: packet(2) });
      expect(service.suggestions).toEqual({ status: "closed" });
    });

    it("drops a suggestions failure that arrives after the review closed", async () => {
      const { service, fetch } = makeReviewService();
      const pendingSuggestions = deferred<object>();
      fetch.mockResolvedValueOnce(packet(1)).mockReturnValueOnce(pendingSuggestions.promise);
      seedReadyModel(service);

      await service.openReview();
      const requested = service.requestSuggestions();
      service.closeReview();
      pendingSuggestions.reject(new Error("late"));
      await requested;

      expect(service.suggestions).toEqual({ status: "closed" });
    });

    it("opens a failure repair at its evidence level and drops a launch that answers after it closed", async () => {
      const { service, fetch } = makeReviewService();
      const lowModel = {
        id: "model-low",
        name: "Low",
        provider: "openai",
        availability: { state: "ready" }
      };
      service.seedState({
        session: makeSession({ session_id: "s-repair", flow_id: "flow-1" }),
        availableModels: [lowModel as never],
        defaultModelId: "model-low",
        modelLoadStatus: "loaded"
      });
      const launch = {
        reference: {
          kind: "run_failure",
          flow_version: 1,
          definition_checksum: "sum-1",
          run_id: "run-1",
          step_order: 2
        },
        evidence_classification_level: 2,
        step_number: 2,
        step_name: "Sammanfatta",
        attempt_no: 1,
        error_code: "typed_io_output_parse_failed"
      };
      const pending = deferred<object>();
      fetch.mockReturnValueOnce(pending.promise);

      const opened = service.openFailureRepair({ runId: "run-1", stepOrder: 2 });
      expect(service.failureRepair.status).toBe("loading");
      service.closeFailureRepair();
      pending.resolve(launch);
      await opened;

      expect(service.failureRepair).toEqual({ status: "closed" });
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(service.activeStepScope).toBeNull();

      // Opened and kept: the listing is asked for at the failure's level. A
      // launch that is closed unsent names no step in the composer.
      fetch
        .mockResolvedValueOnce(launch)
        .mockResolvedValueOnce({ models: [], default_model_id: null });
      await service.openFailureRepair({ runId: "run-1", stepOrder: 2 });
      expect(service.failureRepair).toEqual({ status: "ready", launch });
      expect(fetch.mock.calls[2]?.[1]).toMatchObject({
        params: { query: { evidence_level: 2 } }
      });
      expect(service.activeStepScope).toBeNull();
      service.closeFailureRepair();
      expect(service.activeStepScope).toBeNull();
    });

    it("closes the review when a repair opens, and the repair when a review opens", async () => {
      const { service, fetch } = makeReviewService();
      fetch.mockResolvedValueOnce(packet(1));
      await service.openReview();
      expect(service.review.status).toBe("ready");

      fetch.mockResolvedValueOnce({
        reference: {
          kind: "run_failure",
          flow_version: 1,
          definition_checksum: "sum-1",
          run_id: "r",
          step_order: 1
        },
        evidence_classification_level: 0,
        step_number: 1,
        step_name: null,
        attempt_no: 1,
        error_code: "typed_io_output_parse_failed"
      });
      await service.openFailureRepair({ runId: "r", stepOrder: 1 });
      expect(service.review).toEqual({ status: "closed" });
      expect(service.failureRepair.status).toBe("ready");

      fetch.mockResolvedValueOnce(packet(1));
      await service.openReview();
      expect(service.failureRepair).toEqual({ status: "closed" });
      expect(service.review.status).toBe("ready");
    });

    it("keeps suggestions that answer the review still open", async () => {
      const { service, fetch } = makeReviewService();
      fetch.mockResolvedValueOnce(packet(1)).mockResolvedValueOnce(judged(1));
      seedReadyModel(service);

      await service.openReview();
      await service.requestSuggestions();

      expect(service.suggestions).toEqual({ status: "ready", suggestions: judged(1) });
    });

    it("requests no suggestions while the shown model cannot run, and says why", async () => {
      const { service, fetch } = makeReviewService();
      fetch.mockResolvedValueOnce(packet(1));
      service.seedState({
        availableModels: [
          {
            id: "model-low",
            name: "Low",
            provider: "openai",
            availability: {
              state: "capacity_undeclared",
              missing_dimensions: ["max_input_tokens"]
            }
          }
        ],
        defaultModelId: null,
        modelLoadStatus: "loaded"
      });

      await service.openReview();
      await service.requestSuggestions();

      expect(service.suggestions).toEqual({ status: "closed" });
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(service.modelSendBlock).toBe("no_ready_model");
      expect(service.modelSendBlockMessage).toBe(m.ai_builder_no_ready_model());
    });

    it("keeps an explicit too-small model and explains the blocked send", async () => {
      const { service } = makeReviewService();
      seedReadyModel(service);
      const ready = service.availableModels[0]!;
      service.seedState({
        selectedModelId: "too-small",
        availableModels: [
          ready,
          {
            ...ready,
            id: "too-small",
            name: "Small",
            availability: { state: "capacity_too_small" }
          }
        ]
      });
      expect(service.effectiveModel?.id).toBe("too-small");
      expect(service.modelSendBlock).toBe("model_capacity_too_small");
      expect(service.modelSendBlockMessage).toBe(m.ai_builder_model_capacity_too_small());
      expect(await service.sendMessage("Behåll min text")).toBe("not_started");
      expect(service.effectiveModel?.id).toBe("too-small");
    });

    it("gives every blocked state a reason, so a refused send never goes unexplained", () => {
      const { service } = makeReviewService();
      service.seedState({ modelLoadStatus: "loading" });
      expect(service.modelSendBlockMessage).toBe(m.ai_builder_models_loading());
      service.seedState({ modelLoadStatus: "failed" });
      expect(service.modelSendBlockMessage).toBe(m.failed_to_load_models());
      seedReadyModel(service);
      expect(service.modelSendBlockMessage).toBeNull();
    });
  });

  it("keeps the plan-seen latch for transient re-plan streams", () => {
    const service = makeService();

    expect(service.hasSeenPlanInSession).toBe(false);

    service.seedState({
      session: makeSession(),
      currentPlan: makePlan()
    });

    expect(service.hasSeenPlanInSession).toBe(true);

    service.seedState({
      currentPlan: null,
      streamState: "streaming"
    });

    expect(service.hasSeenPlanInSession).toBe(true);
    expect(service.currentPlan).toBeNull();
    expect(service.isStreaming).toBe(true);
  });

  it("resets and re-engages the plan-seen latch across sessions", () => {
    const service = makeService();

    service.seedState({
      session: makeSession(),
      currentPlan: makePlan()
    });

    expect(service.hasSeenPlanInSession).toBe(true);

    service.seedState({
      session: null,
      currentPlan: makePlan()
    });

    expect(service.hasSeenPlanInSession).toBe(false);

    service.seedState({
      session: makeSession({ session_id: "session-2" }),
      currentPlan: makePlan({ plan_id: "plan-2" })
    });

    expect(service.hasSeenPlanInSession).toBe(true);
  });
});
