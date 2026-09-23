import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import type { Space } from "@eneo/eneo-js";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import type {
  AIBuilderError,
  AIBuilderSession,
  AIBuilderTelemetrySummary,
  ApplyResult,
  ProposedPlan,
  StepSpec
} from "./protocol";
import type { AIBuilderClientTransport, PendingPlanOperation } from "./FlowAIBuilderDriver";
import { tick, type ComponentProps } from "svelte";
import BuilderReviewScreenHarness from "./test-harnesses/BuilderReviewScreenHarness.svelte";

type HarnessProps = ComponentProps<typeof BuilderReviewScreenHarness>;

afterEach(() => {
  cleanup();
});

// A one-step edit: step 2 of two is the scoped target and the only change.
function scopedStepEditState(targetStep: Partial<StepSpec> = {}) {
  return {
    session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
    currentPlan: makePlan({
      proposal: makeProposal({
        spec: {
          flow_name: "Mötesrapport",
          flow_description: "Skriver en rapport.",
          form_fields: [],
          steps: [
            makeTranscribeStep({ existing_step_ref: "existing_step_1" }),
            makeRenderStep({
              existing_step_ref: "existing_step_2",
              name: "Sammanfatta",
              output_mode: "pass_through",
              output_type: "text",
              assistant_spec: {
                instructions: "Skriv en kort sammanfattning.",
                knowledge_refs: [],
                model_ref: null
              },
              ...targetStep
            })
          ]
        },
        edit: {
          base_flow_revision: 3,
          removed_existing_step_refs: [],
          scoped_target_existing_step_ref: "existing_step_2",
          diff: {
            step_changes: [
              { kind: "unchanged", step_name: "Transkribera ljud", step_ref: "existing_step_1" },
              {
                kind: "modified",
                step_name: "Sammanfatta",
                step_ref: "existing_step_2",
                field_changes: [
                  {
                    field: "instructions",
                    previous: "Sammanfatta texten.",
                    current: "Skriv en kort sammanfattning."
                  }
                ]
              }
            ],
            net_steps_added: 0,
            net_steps_removed: 0,
            flow_property_changes: {}
          },
          warnings: [],
          advisories: [],
          risk_flags: [],
          confidence: "ready"
        }
      })
    })
  };
}

describe("BuilderReviewScreen approval", () => {
  it("offers one primary action in create mode and creates only after the dialog", async () => {
    const createFlowFromPlan = vi.fn().mockResolvedValue({
      flow_id: "flow-1",
      flow_name: "Ljud till PDF",
      steps_created: 2,
      steps_updated: 0,
      steps_removed: 0
    });
    const onapplied = vi.fn();

    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState(),
      screenProps: { onapplied },
      onservice: (service) => {
        service.createFlowFromPlan = createFlowFromPlan;
      }
    });

    expect(screen.queryByRole("button", { name: m.ai_builder_apply() })).toBeNull();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve() })).toBeNull();
    const approve = screen.getAllByRole("button", { name: m.ai_builder_approve_create() });
    expect(approve).toHaveLength(1);

    await fireEvent.click(approve[0]);
    expect(await screen.findByText(m.ai_builder_approve_dialog_title())).toBeTruthy();
    expect(createFlowFromPlan).not.toHaveBeenCalled();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm() })
    );
    await waitFor(() => expect(createFlowFromPlan).toHaveBeenCalledOnce());
    // The beat before the callback is covered by the fake-timer test below.
    expect(onapplied).not.toHaveBeenCalled();
  });

  it("keeps the dialog open as the progress surface and opens the flow after a beat", async () => {
    // Confirming leaves the dialog in place: it shows the request in flight,
    // then the created moment, and the flow opens after a fixed beat.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      let service!: Parameters<NonNullable<HarnessProps["onservice"]>>[0];
      let finishCreate!: () => void;
      const createFlowFromPlan = vi.fn(
        () =>
          new Promise<ApplyResult>((resolve) => {
            service.seedState({ pendingOperation: makePendingOperation("creating") });
            finishCreate = () => {
              service.seedState({ pendingOperation: null, applyResult: makeApplyResult() });
              resolve(makeApplyResult());
            };
          })
      );
      const onapplied = vi.fn();
      const { unmount } = render(BuilderReviewScreenHarness, {
        currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
        state: makeCreateState(),
        screenProps: { onapplied },
        onservice: (s) => {
          service = s;
          s.createFlowFromPlan = createFlowFromPlan;
        }
      });

      await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_approve_create() }));
      await fireEvent.click(
        screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm() })
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(createFlowFromPlan).toHaveBeenCalledOnce();

      // Pending: the dialog stays, says so, and neither button works.
      const dialog = screen.getByRole("alertdialog");
      expect(within(dialog).getByText(m.ai_builder_approve_dialog_pending_hint())).toBeTruthy();
      const creating = within(dialog).getByRole("button", { name: m.ai_builder_creating() });
      expect((creating as HTMLButtonElement).disabled).toBe(true);
      const cancel = within(dialog).getByRole("button", {
        name: m.ai_builder_approve_dialog_cancel()
      });
      expect((cancel as HTMLButtonElement).disabled).toBe(true);
      expect(dialog.getAttribute("aria-busy")).toBe("true");
      expect(onapplied).not.toHaveBeenCalled();

      // Created: the same dialog shows the moment (no longer "creating"),
      // then closes and the flow opens.
      finishCreate();
      await vi.advanceTimersByTimeAsync(0);
      expect(within(dialog).getByText(m.ai_builder_approve_dialog_created())).toBeTruthy();
      expect(within(dialog).queryByRole("button", { name: m.ai_builder_creating() })).toBeNull();
      expect(
        within(dialog).getByRole("button", { name: m.ai_builder_approve_dialog_created_action() })
      ).toBeTruthy();
      await vi.advanceTimersByTimeAsync(899);
      expect(onapplied).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(onapplied).toHaveBeenCalledWith(expect.objectContaining({ flow_id: "flow-1" }));
      expect(screen.queryByRole("alertdialog")).toBeNull();
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes the dialog after the beat even when nothing navigates away", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const createFlowFromPlan = vi.fn().mockResolvedValue(makeApplyResult());
      const { unmount } = render(BuilderReviewScreenHarness, {
        currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
        state: makeCreateState(),
        onservice: (s) => {
          s.createFlowFromPlan = createFlowFromPlan;
        }
      });
      await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_approve_create() }));
      await fireEvent.click(
        screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm() })
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(screen.getByRole("alertdialog")).toBeTruthy();
      await vi.advanceTimersByTimeAsync(900);
      expect(screen.queryByRole("alertdialog")).toBeNull();
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes the dialog on a failed create and hands focus to the failure panel", async () => {
    let service!: Parameters<NonNullable<HarnessProps["onservice"]>>[0];
    const createFlowFromPlan = vi.fn(async () => {
      service.seedState({
        pendingOperation: null,
        applyError: makeError("internal"),
        createFailureOutcome: "confirmed_not_applied"
      });
      throw new Error("create failed");
    });
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState(),
      onservice: (s) => {
        service = s;
        s.createFlowFromPlan = createFlowFromPlan;
      }
    });

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_approve_create() }));
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm() })
    );

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    const panel = await screen.findByText(m.ai_builder_create_failed_title());
    const region = panel.closest('[role="status"]') as HTMLElement;
    await waitFor(() => expect(document.activeElement).toBe(region));
    // The primary action offers a retry rather than a dead button.
    expect(screen.getByRole("button", { name: m.ai_builder_turn_retry() })).toBeTruthy();
  });

  it("does not open the flow on behalf of a screen the reader already left", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const createFlowFromPlan = vi.fn().mockResolvedValue({
        flow_id: "flow-1",
        flow_name: "Ljud till PDF",
        steps_created: 2,
        steps_updated: 0,
        steps_removed: 0
      });
      const onapplied = vi.fn();
      const { unmount } = render(BuilderReviewScreenHarness, {
        currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
        state: makeCreateState(),
        screenProps: { onapplied },
        onservice: (service) => {
          service.createFlowFromPlan = createFlowFromPlan;
        }
      });

      await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_approve_create() }));
      await fireEvent.click(
        screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm() })
      );
      await vi.advanceTimersByTimeAsync(0);
      expect(createFlowFromPlan).toHaveBeenCalledOnce();
      unmount();
      await vi.advanceTimersByTimeAsync(1000);
      expect(onapplied).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("replaces the footer actions with the success moment once the flow exists", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        applyResult: {
          flow_id: "flow-1",
          flow_name: "Ljud till PDF",
          steps_created: 2,
          steps_updated: 0,
          steps_removed: 0
        }
      }
    });

    expect(screen.getByText(m.ai_builder_applied_success())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_applied_opening())).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve_create() })).toBeNull();
    expect(screen.queryByRole("button", { name: m.ai_builder_modify() })).toBeNull();
  });

  it("approves and applies an edit with one confirmation, and closes once the host shows the flow", async () => {
    const applyResult = {
      flow_id: "flow-1",
      flow_name: "Flöde",
      steps_created: 0,
      steps_updated: 1,
      steps_removed: 0
    };
    const approvePlan = vi.fn().mockResolvedValue(undefined);
    const applyPlan = vi.fn().mockResolvedValue(applyResult);
    let finishHandoff: () => void = () => {};
    const onapplied = vi.fn(() => new Promise<void>((resolve) => (finishHandoff = resolve)));
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval" }),
        currentPlan: makePlan({ status: "proposed" })
      },
      screenProps: { onapplied },
      onservice: (service) => {
        service.approvePlan = approvePlan;
        service.applyPlan = applyPlan;
      }
    });
    // One primary action; a draft hears nothing about unpublishing.
    expect(screen.getByRole("button", { name: m.ai_builder_approve() })).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.ai_builder_apply() })).toBeNull();
    expect(screen.queryByRole("button", { name: m.ai_builder_approve_create() })).toBeNull();
    expect(screen.queryByText(m.ai_builder_footer_edit_unpublishes())).toBeNull();
    expect(screen.queryByText(m.ai_builder_footer_draft_not_running())).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_approve() }));
    // An edit's description already says no run starts; the list does not repeat it.
    const dialog = within(screen.getByRole("alertdialog"));
    expect(dialog.queryByText(m.ai_builder_approve_dialog_no_data())).toBeNull();
    expect(dialog.getByText(m.ai_builder_approve_dialog_step_editable())).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm_edit() })
    );
    await waitFor(() =>
      expect(onapplied).toHaveBeenCalledWith({
        flow_id: "flow-1",
        focusStepIndex: expect.anything()
      })
    );
    expect(approvePlan).toHaveBeenCalledOnce();
    expect(applyPlan).toHaveBeenCalledOnce();
    expect(approvePlan.mock.invocationCallOrder[0]).toBeLessThan(
      applyPlan.mock.invocationCallOrder[0]
    );
    // The dialog is the progress surface until the host has shown the flow:
    // the screen's applied state never flashes past.
    expect(screen.getByRole("alertdialog").getAttribute("data-state")).toBe("open");
    expect(screen.getByText(m.ai_builder_approve_dialog_pending_hint_edit())).toBeTruthy();
    // The button keeps the dialog's verb while it works.
    expect(dialog.getByRole("button", { name: m.ai_builder_updating_flow() })).toBeTruthy();
    finishHandoff();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("keeps an approved edit whose apply failed, and applies it later without approving again", async () => {
    // A server that reports what it did: approved after approve, applied only
    // after an apply that went through.
    const routes: string[] = [];
    let applyAttempts = 0;
    let approved = false;
    let applied = false;
    const transport = {
      fetch: vi.fn(async (route: string) => {
        routes.push(route);
        if (route === "/api/v1/flows/ai-builder/plans/{plan_id}/approve") {
          approved = true;
          return {};
        }
        if (route === "/api/v1/flows/ai-builder/plans/{plan_id}/apply") {
          applyAttempts += 1;
          if (applyAttempts === 1) throw new TypeError("Failed to fetch");
          applied = true;
          return {
            flow_id: "flow-1",
            flow_name: "Flöde",
            steps_created: 0,
            steps_updated: 1,
            steps_removed: 0
          };
        }
        if (route === "/api/v1/flows/ai-builder/sessions/{session_id}") {
          return makeSession({
            status: applied ? "applied" : "awaiting_approval",
            latest_plan_id: "plan-1"
          });
        }
        if (route === "/api/v1/flows/ai-builder/plans/{plan_id}") {
          return makePlan({ status: applied ? "applied" : approved ? "approved" : "proposed" });
        }
        throw new Error(`Unexpected route ${route}`);
      }),
      stream: vi.fn()
    };
    const onapplied = vi.fn(async () => {});
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
        currentPlan: makePlan({ status: "proposed" })
      },
      transport: transport as never,
      screenProps: { onapplied }
    });

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_approve() }));
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm_edit() })
    );
    // The approval stands; the failed apply closes the dialog and leaves the
    // footer offering the apply alone.
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onapplied).not.toHaveBeenCalled();
    const applyButton = await screen.findByRole("button", { name: m.ai_builder_apply() });

    await fireEvent.click(applyButton);
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm_edit() })
    );
    await waitFor(() => expect(onapplied).toHaveBeenCalledOnce());
    expect(routes.filter((route) => route.endsWith("/approve"))).toHaveLength(1);
    expect(applyAttempts).toBe(2);
  });

  it("announces a new proposal, not the session refresh that stamps the same one", async () => {
    let service!: Parameters<
      NonNullable<ComponentProps<typeof BuilderReviewScreenHarness>["onservice"]>
    >[0];
    // The streamed plan carries no server stamps; the refresh after the turn adds them.
    const streamed = makePlan({ status: "proposed" });
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval" }),
        currentPlan: streamed
      },
      onservice: (instance) => (service = instance)
    });
    service.seedState({
      currentPlan: { ...streamed, updated_at: "2026-09-23T10:00:00Z", spec_hash: "hash-1" }
    });
    await tick();
    expect(screen.queryByText(m.ai_builder_plan_updated_announce())).toBeNull();

    service.seedState({
      currentPlan: {
        ...streamed,
        plan_id: "plan-2",
        updated_at: "2026-09-23T10:05:00Z",
        spec_hash: "hash-2"
      }
    });
    expect(await screen.findByText(m.ai_builder_plan_updated_announce())).toBeTruthy();
  });

  it("applies an already approved edit without approving again, and names publishing only when published", async () => {
    const approvePlan = vi.fn();
    const applyPlan = vi.fn().mockResolvedValue({
      flow_id: "flow-1",
      flow_name: "Flöde",
      steps_created: 0,
      steps_updated: 1,
      steps_removed: 0
    });
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeSession({ status: "awaiting_approval" }),
        currentPlan: makePlan({ status: "approved" })
      },
      screenProps: { flowIsPublished: true },
      onservice: (service) => {
        service.approvePlan = approvePlan;
        service.applyPlan = applyPlan;
      }
    });
    expect(screen.getByText(m.ai_builder_footer_edit_unpublishes())).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_apply() }));
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_approve_dialog_confirm_edit() })
    );
    await waitFor(() => expect(applyPlan).toHaveBeenCalledOnce());
    expect(approvePlan).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("makes no persistence claim and blocks mutation on an unknown create outcome", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        ...makeCreateState(),
        applyError: makeError("unknown"),
        createFailureOutcome: "unknown"
      }
    });

    expect(screen.getByText(m.ai_builder_create_unknown_title())).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_create_failed_body())).toBeNull();
    expect(screen.queryByText(m.ai_builder_plan_unchanged())).toBeNull();
    expect(
      screen.getByRole("button", { name: m.ai_builder_turn_retry() }).hasAttribute("disabled")
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: m.ai_builder_modify() }).hasAttribute("disabled")
    ).toBe(true);
  });

  it("blocks creating an audio plan without an accessible transcription model", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: false }] }),
      state: makeCreateState()
    });

    expect(screen.getByText(m.ai_builder_missing_transcription_model_title())).toBeTruthy();
    expect(
      screen.getByRole("button", { name: m.ai_builder_approve_create() }).hasAttribute("disabled")
    ).toBe(true);
  });
});

describe("BuilderReviewScreen plan document", () => {
  it("shows cumulative planning token usage in the header with details on demand", async () => {
    const state = makeCreateState();
    state.session.telemetry = {
      planner_request_count: 2,
      clarification_question_count: 1,
      prompt_tokens_total: 18_705,
      completion_tokens_total: 6_395,
      total_tokens_total: 25_100,
      tool_call_count_total: 2,
      auxiliary_llm_call_count: 0,
      architecture_commit_count: 1,
      repair_attempts_total: 0,
      parse_repair_attempts_total: 0,
      wall_clock_ms_total: 12_000,
      llm_calls_made_total: 2,
      token_usage_estimated: false,
      last_request_id: "request-2",
      last_model: "Model A",
      last_finish_reason: "tool_calls",
      last_outcome_kind: "dispatched",
      last_token_usage_source: "provider",
      last_token_usage_estimated: false
    };
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state
    });

    const badge = screen.getByRole("button", { name: /25.100 tokens/ });
    await fireEvent.click(badge);

    expect(await screen.findByText(m.flow_run_token_usage_title())).toBeTruthy();
    expect(screen.getByText(/18.705/)).toBeTruthy();
    expect(screen.getByText(/6.395/)).toBeTruthy();
    expect(screen.getByText(m.ai_builder_token_usage_provider_note())).toBeTruthy();
  });

  it("marks review checkpoints, per-file steps and artifacts from the plan spec", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState()
    });

    expect(screen.getAllByText(m.ai_builder_node_review_checkpoint()).length).toBeGreaterThan(0);
    expect(screen.getAllByText(m.ai_builder_node_per_file()).length).toBeGreaterThan(0);
    // The node says what the step answers with, the artifact included.
    expect(
      screen.getAllByText(new RegExp(`${m.ai_builder_answer_pdf_phrase()}$`)).length
    ).toBeGreaterThan(0);
    expect(screen.getByText(m.ai_builder_review_checkpoint_note({ count: 1 }))).toBeTruthy();
  });

  it("presents informational lint as notes, not as quality warnings to fix", () => {
    // A pre-existing gap on a step this edit did not touch is a fact about
    // the flow; it must not count as a quality warning or ask for work.
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        currentPlan: makePlan({
          proposal: makeProposal({
            lint_warnings: [
              {
                step_ref: "step_a",
                code: "json_output_no_contract",
                message: "Step has output_type 'json' but no output_contract. Set output_fields.",
                field_name: null,
                severity: "info"
              }
            ]
          })
        })
      }
    });

    expect(screen.queryByText(m.ai_builder_quality_warnings())).toBeNull();
    expect(screen.getByText(m.ai_builder_flow_notes())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_flow_note_json_output_no_contract())).toBeTruthy();
    expect(screen.queryByText(/Set output_fields/)).toBeNull();
  });

  it("never shows the critic's raw repair text for any informational code", () => {
    // The real package emitted json_output_text_interpolation on an untouched
    // step; its message is a repair instruction for the model, not for people.
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        currentPlan: makePlan({
          proposal: makeProposal({
            lint_warnings: [
              {
                step_ref: "step_c",
                code: "json_output_text_interpolation",
                message: "Prefer output.structured.<field> when only specific fields are needed.",
                field_name: null,
                severity: "info"
              },
              {
                step_ref: "step_c",
                code: "some_future_code",
                message: "Internal repair guidance.",
                field_name: null,
                severity: "info"
              }
            ]
          })
        })
      }
    });

    expect(screen.getByText(m.ai_builder_flow_note_json_output_text_interpolation())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_flow_note_generic())).toBeTruthy();
    expect(screen.queryByText(/Prefer output\.structured/)).toBeNull();
    expect(screen.queryByText("Internal repair guidance.")).toBeNull();
  });

  it("counts only actionable warnings in the quality section", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        currentPlan: makePlan({
          proposal: makeProposal({
            lint_warnings: [
              {
                step_ref: "step_a",
                code: "citations_disabled",
                message: "Källhänvisningar inaktiverades.",
                field_name: null,
                severity: "warning"
              },
              {
                step_ref: "step_a",
                code: "json_output_no_contract",
                message: "Set output_fields.",
                field_name: null,
                severity: "info"
              }
            ]
          })
        })
      }
    });

    expect(screen.getByText(m.ai_builder_quality_warnings())).toBeTruthy();
    expect(screen.getByText("Källhänvisningar inaktiverades.")).toBeTruthy();
    expect(screen.getByText(m.ai_builder_flow_notes())).toBeTruthy();
    expect(screen.queryByText("Set output_fields.")).toBeNull();
  });

  it("names the step a quality warning is about by its number and name", () => {
    // The critic refers to steps by their plan reference; the reader knows
    // them by the numbered names on the diagram. An unknown reference still
    // shows rather than hiding the warning.
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        currentPlan: makePlan({
          proposal: makeProposal({
            lint_warnings: [
              {
                step_ref: "step_a",
                code: "citations_disabled",
                message: "Källhänvisningar inaktiverades.",
                field_name: null
              },
              { step_ref: "step_zz", code: "unknown", message: "Okänt steg.", field_name: null }
            ]
          })
        })
      }
    });

    const firstStepName = makeTranscribeStep().name;
    expect(screen.getByText(`1. ${firstStepName}`)).toBeTruthy();
    expect(screen.queryByText("step_a")).toBeNull();
    expect(screen.getByText("step_zz")).toBeTruthy();
  });

  it("distinguishes the space default model from deterministic steps", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        currentPlan: makePlan({
          proposal: makeProposal({
            spec: {
              flow_name: "Ljud till PDF",
              flow_description: "",
              form_fields: [],
              steps: [
                makeRenderStep({
                  name: "Analysera samtalet",
                  output_mode: "pass_through",
                  output_type: "json"
                }),
                makeRenderStep({
                  plan_step_ref: "step_c",
                  output_mode: "render_verbatim"
                })
              ]
            }
          })
        })
      }
    });

    expect(screen.getAllByText(m.ai_builder_node_model_space_default()).length).toBeGreaterThan(0);
    // The DIAGRAM chip describes what the mechanical step does…
    expect(screen.getAllByText(m.ai_builder_node_mode_render_verbatim()).length).toBeGreaterThan(0);
    // …while the Details view keeps the model-scoped wording under its
    // "Model" heading — the action text must not leak there. Both views stay
    // mounted, so the negative check is scoped to the details panel.
    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    const detailsPanel = screen
      .getAllByRole("tabpanel")
      .find((panel) => within(panel).queryAllByText(m.ai_builder_node_model_none()).length > 0);
    expect(detailsPanel).toBeTruthy();
    expect(
      within(detailsPanel as HTMLElement).queryByText(m.ai_builder_node_mode_render_verbatim())
    ).toBeNull();
  });

  it("keeps a one-step edit's review to the step and counts only what changes", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: scopedStepEditState()
    });

    // The heading and the step card name the step; the list said it again.
    expect(screen.queryByTestId("edit-change-list")).toBeNull();
    // "Change your answers" sends an unscoped turn that would drop the step scope.
    expect(screen.queryByRole("button", { name: m.ai_builder_modify() })).toBeNull();
    expect(
      screen.getByText(m.ai_builder_footer_steps_change_when_approved({ count: 1 }))
    ).toBeTruthy();
    // The step leads the page; the flow card adds no count chips to the
    // footer's count.
    expect(screen.getByTestId("scoped-change-card")).toBeTruthy();
    expect(screen.queryByText(m.ai_builder_diff_modified_one({ count: "1" }))).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_approve() }));
    expect(
      await screen.findByText(m.ai_builder_approve_dialog_steps_edit({ changed: 1, unchanged: 1 }))
    ).toBeTruthy();
  });

  it("keeps the request beside the change, not a later confirmation", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...scopedStepEditState(),
        messages: [
          { role: "user", content: "Gör sammanfattningen kortare.", timestamp: 1 },
          { role: "assistant", content: "Så här förstår jag det.", timestamp: 2 },
          {
            role: "user",
            content: "Det stämmer.",
            metadata: { requirements_confirmed: true },
            timestamp: 3
          }
        ]
      }
    });

    const context = screen.getByRole("complementary", {
      name: m.ai_builder_review_context_label()
    });
    expect(within(context).getByText("Gör sammanfattningen kortare.")).toBeTruthy();
    expect(within(context).queryByText("Det stämmer.")).toBeNull();
    // A one-step change leaves out how the whole flow runs.
    expect(
      within(context).queryByRole("button", { name: m.ai_builder_execution_profile() })
    ).toBeNull();
  });

  it("reads a reference to a planned step as that step, not as the plan's key", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: scopedStepEditState({
        assistant_spec: {
          instructions: "Sammanfatta {{ step_a.output.text }} kort.",
          knowledge_refs: [],
          model_ref: null
        },
        input_bindings: {
          question:
            "Underlag:\n{{step_a.output.text}}\nRubrik: {{ step_a.output.structured.title }}\n" +
            "Beslut: {{ step_a.output.structured.decision }}\nFält: {{ flow_input.namn }}"
        }
      })
    });

    expect((await screen.findByTitle("{{ step_a.output.text }}")).textContent?.trim()).toBe(
      "1. Transkribera ljud"
    );
    expect(screen.getByTitle("{{step_a.output.text}}").textContent?.trim()).toBe(
      "1. Transkribera ljud"
    );
    // A field of the step keeps its path, so two fields never read alike.
    expect(screen.getByTitle("{{ step_a.output.structured.title }}").textContent?.trim()).toBe(
      "1. Transkribera ljud · output.structured.title"
    );
    expect(screen.getByTitle("{{ step_a.output.structured.decision }}").textContent?.trim()).toBe(
      "1. Transkribera ljud · output.structured.decision"
    );
    // The words around a reference keep their spacing and line breaks, and a
    // token that names no planned step stays as written.
    const paragraphs = [...document.querySelectorAll("p")].map((p) => p.textContent);
    expect(paragraphs).toContain("Sammanfatta 1. Transkribera ljud kort.");
    expect(paragraphs).toContain(
      "Underlag:\n1. Transkribera ljud\nRubrik: 1. Transkribera ljud · output.structured.title\n" +
        "Beslut: 1. Transkribera ljud · output.structured.decision\nFält: {{ flow_input.namn }}"
    );
  });

  it("shows what an edit changes in a published step and opens that step first", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
        currentPlan: makePlan({
          proposal: makeProposal({
            spec: {
              flow_name: "Mötesrapport",
              flow_description: "Skriver en rapport.",
              form_fields: [],
              steps: [
                makeTranscribeStep({ existing_step_ref: "existing_step_1" }),
                makeRenderStep({
                  existing_step_ref: "existing_step_2",
                  name: "Strukturera transkriberingen",
                  output_mode: "pass_through",
                  output_type: "json",
                  output_contract: {
                    type: "object",
                    properties: { talare: { type: "array" } }
                  },
                  assistant_spec: {
                    instructions: "Strukturera texten källnära.",
                    knowledge_refs: [],
                    model_ref: null
                  }
                })
              ]
            },
            edit: {
              base_flow_revision: 3,
              removed_existing_step_refs: [],
              scoped_target_existing_step_ref: null,
              diff: {
                step_changes: [
                  {
                    kind: "unchanged",
                    step_name: "Transkribera ljud",
                    step_ref: "existing_step_1"
                  },
                  {
                    kind: "modified",
                    step_name: "Strukturera transkriberingen",
                    step_ref: "existing_step_2",
                    field_changes: [
                      {
                        field: "name",
                        previous: "Strukturera",
                        current: "Strukturera transkriberingen"
                      },
                      { field: "output_type", previous: "text", current: "json" },
                      {
                        field: "output_contract",
                        previous: "talare",
                        current: "talare",
                        previous_detail:
                          '{"properties":{"talare":{"type":"string"}},"type":"object"}',
                        current_detail: '{"properties":{"talare":{"type":"array"}},"type":"object"}'
                      },
                      { field: "review_policy", previous: null, current: "view" },
                      {
                        field: "instructions",
                        previous: "Skriv om texten fritt.",
                        current: "Strukturera texten källnära."
                      }
                    ]
                  }
                ],
                net_steps_added: 0,
                net_steps_removed: 0,
                flow_property_changes: {}
              },
              warnings: [],
              advisories: [],
              risk_flags: [],
              confidence: "ready"
            }
          })
        })
      }
    });

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    // The changed step is open on its own; the untouched one waits behind "Visa".
    const changedTrigger = screen.getByRole("button", {
      name: stepCard(2, "Strukturera transkriberingen")
    });
    await waitFor(() => expect(changedTrigger.getAttribute("aria-expanded")).toBe("true"));
    expect(screen.queryByRole("button", { name: stepCard(1, "Transkribera ljud") })).toBeNull();
    expect(screen.getByText(m.ai_builder_review_unchanged_hidden_one())).toBeTruthy();
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_review_unchanged_show() })
    );
    expect(
      (await screen.findByRole("button", { name: stepCard(1, "Transkribera ljud") })).getAttribute(
        "aria-expanded"
      )
    ).toBe("false");

    const changes = await screen.findByTestId("step-field-changes");
    // One sentence says what the answer becomes, naming the field.
    expect(
      within(changes).getByText(m.ai_builder_change_sentence_fields_named_one({ fields: "talare" }))
    ).toBeTruthy();
    // The step's three parts: what it reads stays; what it does and answers with change.
    const parts = within(changes)
      .getAllByRole("listitem")
      .map((li) => li.textContent?.replace(/\s+/g, " ").trim() ?? "");
    expect(parts).toHaveLength(3);
    expect(parts[0]).toContain(m.ai_builder_reads_previous());
    expect(parts[0]).toContain(m.ai_builder_change_tag_unchanged());
    expect(parts[1]).toContain(m.ai_builder_change_does_instruction());
    expect(parts[1]).toContain(m.ai_builder_change_tag_changes());
    expect(parts[2]).toContain(
      `${m.ai_builder_step_change_previous_label()}: ${m.ai_builder_answer_text()}`
    );
    expect(parts[2]).toContain(
      `${m.ai_builder_step_change_current_label()}: ${m.ai_builder_answer_fields_one()}`
    );
    // The new field, then the changes no part tells: the name and the review.
    expect(
      within(changes)
        .getAllByRole("term")
        .map((dt) => dt.textContent?.trim())
    ).toEqual(["Talare", m.ai_builder_step_change_field_name(), m.flow_step_review_policy()]);
    const rows = within(changes)
      .getAllByRole("definition")
      .map((dd) => dd.textContent?.replace(/\s+/g, " ").trim());
    // The arrow between the values is drawn; the labels carry the order.
    expect(rows.slice(1)).toEqual([
      `${m.ai_builder_step_change_previous_label()}: Strukturera ${m.ai_builder_step_change_current_label()}: Strukturera transkriberingen`,
      `${m.ai_builder_step_change_previous_label()}: ${m.flow_step_review_policy_none()} ${m.ai_builder_step_change_current_label()}: ${m.flow_step_review_policy_view()}`
    ]);
    // Both wordings of the instruction wait behind one fold in the "does" part.
    const fold = within(changes).getByRole("button", {
      name: m.ai_builder_change_show_before_after()
    });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(fold);
    await waitFor(() =>
      expect(
        within(changes)
          .getByRole("button", { name: m.ai_builder_change_hide_before_after() })
          .getAttribute("aria-expanded")
      ).toBe("true")
    );
    expect(await within(changes).findByText("Skriv om texten fritt.")).toBeTruthy();
  });

  it("reads one list of what an edit changes, removed steps included", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
        currentPlan: makePlan({
          proposal: makeProposal({
            spec: {
              flow_name: "Mötesrapport",
              flow_description: "Skriver en kort rapport.",
              form_fields: [],
              steps: [
                makeTranscribeStep({ existing_step_ref: "existing_step_1" }),
                makeRenderStep({
                  existing_step_ref: "existing_step_2",
                  name: "Strukturera transkriberingen"
                }),
                makeRenderStep({ plan_step_ref: "step_c", name: "Sammanfatta" })
              ]
            },
            edit: {
              base_flow_revision: 3,
              removed_existing_step_refs: ["existing_step_3"],
              scoped_target_existing_step_ref: null,
              scoped_target_plan_step_ref: null,
              diff: {
                step_changes: [
                  {
                    kind: "unchanged",
                    step_name: "Transkribera ljud",
                    step_ref: "existing_step_1"
                  },
                  {
                    kind: "modified",
                    step_name: "Strukturera transkriberingen",
                    step_ref: "existing_step_2",
                    field_changes: [
                      { field: "output_type", previous: "text", current: "json" },
                      { field: "instructions", previous: "Fritt.", current: "Källnära." }
                    ]
                  },
                  { kind: "added", step_name: "Sammanfatta", step_ref: null },
                  { kind: "removed", step_name: "Skicka e-post", step_ref: "existing_step_3" }
                ],
                flow_property_changes: {
                  flow_name: ["Möte", "Mötesrapport"],
                  flow_description: ["Skriver en rapport.", "Skriver en kort rapport."]
                },
                form_changes: [
                  { kind: "added", field_name: "diarienummer", details: null },
                  { kind: "removed", field_name: "ort", details: null },
                  { kind: "removed", field_name: "datum", details: null }
                ]
              },
              warnings: [],
              advisories: [],
              risk_flags: [],
              confidence: "ready"
            }
          })
        })
      }
    });

    const list = screen.getByTestId("edit-change-list");
    const rows = within(list)
      .getAllByRole("listitem")
      .map((li) => li.textContent?.replace(/\s+/g, " ").trim());
    // "Utdata och instruktioner ändras": the field labels the details view
    // uses, read as one sentence.
    const fieldsSentence = m.ai_builder_change_list_fields_changed({
      fields: `${m.ai_builder_step_change_field_output_type().toLowerCase()} ${m.ai_builder_review_suggestion_steps_join()} ${m.ai_builder_step_instructions().toLowerCase()}`
    });
    expect(rows).toEqual([
      `${m.ai_builder_change_list_name()} ${m.ai_builder_change_list_name_what({ name: "Mötesrapport" })}`,
      `${m.ai_builder_change_list_description()} ${m.ai_builder_change_list_description_what()}`,
      `${m.ai_builder_change_request_scope({ step: 2, name: "Strukturera transkriberingen" })} ${fieldsSentence.charAt(0).toUpperCase()}${fieldsSentence.slice(1)}`,
      `${m.ai_builder_change_request_scope({ step: 3, name: "Sammanfatta" })} ${m.ai_builder_change_list_new_step()}`,
      `Skicka e-post ${m.ai_builder_change_list_removed()}`,
      `${m.ai_builder_form_fields_title()} ${m.ai_builder_change_list_form_added({ count: "1" })} ${m.ai_builder_review_suggestion_steps_join()} ${m.ai_builder_change_list_form_removed({ count: "2" })}`
    ]);
    // The list is the only place a removed step is read.
    expect(screen.getAllByText("Skicka e-post")).toHaveLength(1);

    // An entry opens its step in the details view.
    await fireEvent.click(
      within(list).getByRole("button", {
        name: `${m.ai_builder_change_request_scope({ step: 3, name: "Sammanfatta" })} ${m.ai_builder_change_list_new_step()}`
      })
    );
    const trigger = await screen.findByRole("button", { name: stepCard(3, "Sammanfatta") });
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("true"));
    // The handoff lands on the step, not back at the top of the document.
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("says honestly when the proposal changes nothing", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        session: makeSession({ status: "awaiting_approval", latest_plan_id: "plan-1" }),
        currentPlan: makePlan({
          proposal: makeProposal({
            spec: {
              flow_name: "Mötesrapport",
              flow_description: "Skriver en rapport.",
              form_fields: [],
              steps: [
                makeTranscribeStep({ existing_step_ref: "existing_step_1" }),
                makeRenderStep({ existing_step_ref: "existing_step_2" })
              ]
            },
            edit: {
              base_flow_revision: 3,
              removed_existing_step_refs: [],
              scoped_target_existing_step_ref: null,
              scoped_target_plan_step_ref: null,
              diff: {
                step_changes: [
                  {
                    kind: "unchanged",
                    step_name: "Transkribera ljud",
                    step_ref: "existing_step_1"
                  },
                  { kind: "unchanged", step_name: "Skriv rapport", step_ref: "existing_step_2" }
                ],
                flow_property_changes: {}
              },
              warnings: [],
              advisories: [],
              risk_flags: [],
              confidence: "ready"
            }
          })
        })
      }
    });

    const list = screen.getByTestId("edit-change-list");
    expect(within(list).getByText(m.ai_builder_change_list_none())).toBeTruthy();
    expect(within(list).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("keeps an expanded step expanded across Diagram↔Detaljer switches", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState()
    });

    const detailsTab = screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() });
    await fireEvent.click(detailsTab);
    await waitFor(() => expect(detailsTab.getAttribute("data-state")).toBe("active"));

    const trigger = () => screen.getByRole("button", { name: stepCard(1, "Transkribera ljud") });
    await fireEvent.click(trigger());
    await waitFor(() => expect(trigger().getAttribute("aria-expanded")).toBe("true"));

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_diagram() }));
    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    await waitFor(() => expect(trigger().getAttribute("aria-expanded")).toBe("true"));
  });
});

describe("BuilderReviewScreen change requests", () => {
  it("scopes the change box to a step and sends that step's edit context", async () => {
    const sendMessage = vi.fn().mockResolvedValue("delivered");
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState(),
      onservice: (service) => {
        service.sendMessage = sendMessage;
      }
    });

    await fireEvent.click(screen.getByRole("tab", { name: m.ai_builder_canvas_tab_details() }));
    await fireEvent.click(screen.getByRole("button", { name: stepCard(2, "Rendera PDF") }));
    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_step_request_change({ step: 2 }) })
    );

    expect(
      await screen.findByText(m.ai_builder_change_request_scope({ step: 2, name: "Rendera PDF" }))
    ).toBeTruthy();

    const textarea = screen.getByLabelText(m.ai_builder_change_request_textarea_label());
    await fireEvent.input(textarea, { target: { value: "Lägg till en försättssida" } });
    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_send() }));

    expect(sendMessage).toHaveBeenCalledWith("Lägg till en försättssida", undefined, undefined, {
      kind: "proposed_plan",
      scope: "step",
      plan_id: "plan-1",
      target_plan_step_ref: "step_b",
      target_existing_step_ref: null,
      target_step_name: "Rendera PDF",
      target_step_number: 2
    });
  });

  it("locks approval and shows the overlay while a revision streams", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: { ...makeCreateState(), streamState: "streaming" }
    });

    expect(screen.getByText(m.ai_builder_revising_overlay())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_footer_locked_while_revising())).toBeTruthy();
    expect(
      screen.getByRole("button", { name: m.ai_builder_approve_create() }).hasAttribute("disabled")
    ).toBe(true);
  });

  it("keeps the plan and shows a dismissible notice when the reply carried no new plan", async () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: {
        ...makeCreateState(),
        reviewNote: "Jag kan inte byta modell åt dig — det gör du i stegredigeraren."
      }
    });

    expect(screen.getByRole("heading", { name: "Ljud till PDF" })).toBeTruthy();
    expect(
      screen.getByText("Jag kan inte byta modell åt dig — det gör du i stegredigeraren.")
    ).toBeTruthy();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_review_note_acknowledge() })
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Jag kan inte byta modell åt dig — det gör du i stegredigeraren.")
      ).toBeNull()
    );
  });

  it("marks the steps a replacement plan changed", async () => {
    let seed: ((state: object) => void) | undefined;
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: makeCreateState(),
      onservice: (service) => (seed = (state) => service.seedState(state))
    });

    expect(screen.queryByText(m.ai_builder_node_updated())).toBeNull();

    seed!({
      currentPlan: makePlan({
        plan_id: "plan-2",
        status: "proposed",
        proposal: makeProposal({
          spec: {
            flow_name: "Ljud till PDF",
            flow_description: "",
            form_fields: [],
            steps: [
              makeTranscribeStep(),
              makeRenderStep({
                assistant_spec: {
                  instructions: "Rendera PDF med en försättssida.",
                  knowledge_refs: [],
                  model_ref: null
                }
              })
            ]
          }
        })
      })
    });

    expect(await screen.findByText(m.ai_builder_plan_updated_detail({ count: 1 }))).toBeTruthy();
    expect(screen.getAllByText(m.ai_builder_node_updated()).length).toBeGreaterThan(0);
  });
});

describe("BuilderReviewScreen recovery surfaces", () => {
  it("renders one conflict card for a stream conflict and clears it when the reload succeeds", async () => {
    // The stale conflict is also persisted on the committed turn, so a
    // refresh alone would rehydrate it; recovery must end with the card gone
    // and the reloaded plan on screen.
    const reloadedSession = makeSession({
      status: "awaiting_approval",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: "plan-2",
      latest_turn: {
        client_turn_id: "11111111-1111-4111-8111-111111111111",
        state: "committed",
        user_message_id: "11111111-1111-4111-8111-111111111112",
        error: {
          schema_version: 2,
          code: "stale_plan_revision",
          category: "conflict",
          message: "Planen ändrades",
          phase: "planner",
          eneo_error_code: 9000,
          request_id: "req-1",
          diagnostic_context: null,
          details: {}
        },
        requires_duplicate_provider_spend_acknowledgement: false,
        retry_request: {
          client_turn_id: "11111111-1111-4111-8111-111111111111",
          message: "Lägg till ett steg",
          model_id: null,
          ui_language: "sv",
          acknowledge_duplicate_provider_spend: false
        }
      }
    });
    const transport = {
      fetch: vi.fn(async (route: string) =>
        route.endsWith("/sessions/{session_id}") ? reloadedSession : makePlan({ plan_id: "plan-2" })
      ),
      stream: vi.fn()
    } as unknown as AIBuilderClientTransport;
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: { ...makeCreateState(), error: makeError("stale_plan_revision") },
      transport
    });

    expect(screen.getAllByText(m.ai_builder_conflict_elsewhere_title())).toHaveLength(1);
    expect(screen.getByText(m.ai_builder_conflict_stale_plan())).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_conflict_refresh() }));

    await waitFor(() => {
      expect(screen.queryByText(m.ai_builder_conflict_elsewhere_title())).toBeNull();
    });
    expect(screen.getByRole("button", { name: m.ai_builder_approve_create() })).toBeTruthy();
  });

  it("keeps the conflict card when the reload fails", async () => {
    const transport = {
      fetch: vi.fn(async () => {
        throw new Error("offline");
      }),
      stream: vi.fn()
    } as unknown as AIBuilderClientTransport;
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [{ can_access: true }] }),
      state: { ...makeCreateState(), error: makeError("stale_plan_revision") },
      transport
    });

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_conflict_refresh() }));
    await waitFor(() => expect(transport.fetch).toHaveBeenCalled());

    expect(screen.getAllByText(m.ai_builder_conflict_elsewhere_title())).toHaveLength(1);
  });

  it("offers only the cost-acknowledging retry for an unknown provider outcome", async () => {
    const acknowledge = vi.fn();
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeRecoverableSession("provider_outcome_unknown"),
        currentPlan: null,
        error: makeError("unknown")
      },
      screenProps: { showGenerationFailure: true },
      onservice: (service) => {
        service.acknowledgeAndRetryLatestTurn = acknowledge;
      }
    });

    expect(
      screen.getByRole("heading", {
        name: m.ai_builder_failure_heading_provider_outcome_unknown()
      })
    ).toBeTruthy();
    expect(
      screen.getByText(new RegExp(m.ai_builder_failure_cause_provider_outcome_unknown()))
    ).toBeTruthy();
    // One action, and it says what it does; no plain retry, no reword offer.
    expect(screen.queryByRole("button", { name: m.ai_builder_turn_retry() })).toBeNull();
    expect(
      screen.queryByRole("button", { name: m.ai_builder_failure_action_clarify() })
    ).toBeNull();

    await fireEvent.click(
      screen.getByRole("button", { name: m.ai_builder_turn_retry_with_cost_acknowledgement() })
    );
    expect(acknowledge).toHaveBeenCalledOnce();
  });

  it("offers the safe retry alone for a pre-provider failure that fences new messages", () => {
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeRecoverableSession("failed_before_provider"),
        currentPlan: null,
        error: makeError("unknown")
      },
      screenProps: { showGenerationFailure: true }
    });

    expect(
      screen.getByText(new RegExp(m.ai_builder_turn_failed_before_provider_description()))
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: m.ai_builder_turn_retry() })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: m.ai_builder_turn_retry_with_cost_acknowledgement() })
    ).toBeNull();
    // The composer would refuse a new message here, so no rewording is offered.
    expect(
      screen.queryByRole("button", { name: m.ai_builder_failure_action_clarify() })
    ).toBeNull();
    // The way back to the conversation lives in the header, not in the card.
    expect(screen.queryByRole("button", { name: m.ai_builder_show_conversation() })).toBeNull();
  });

  it("names a committed provider rejection, sends the request again, and opens once", async () => {
    const resend = vi.fn().mockResolvedValue("delivered");
    let service!: Parameters<NonNullable<HarnessProps["onservice"]>>[0];
    render(BuilderReviewScreenHarness, {
      currentSpace: makeSpace({ transcriptionModels: [] }),
      state: {
        session: makeRecoverableSession("committed"),
        currentPlan: null,
        error: {
          ...makeError("planner_upstream_error"),
          category: "upstream",
          request_id: "req-42",
          details: {
            another_call_permitted: false,
            provider_disposition: "known_rejection",
            retry_scope: "new_turn"
          }
        }
      },
      screenProps: { showGenerationFailure: true },
      onservice: (s) => {
        service = s;
        s.resendLatestTurn = resend;
      }
    });

    const heading = screen.getByRole("heading", {
      name: m.ai_builder_failure_heading_provider_rejected()
    });
    expect(screen.queryByText("Något gick fel")).toBeNull();
    expect(screen.getByText(new RegExp(m.ai_builder_failure_preserved_create()))).toBeTruthy();
    // The technical facts sit in one quiet line, after the actions.
    const technical = screen.getByText(
      new RegExp(m.ai_builder_failure_technical_code({ code: "planner_upstream_error" }))
    );
    expect(technical.closest("p")?.textContent).toContain(
      m.ai_builder_failure_technical_request({ request: "req-42" })
    );
    const primary = screen.getByRole("button", { name: m.ai_builder_turn_retry() });
    expect(
      primary.compareDocumentPosition(technical) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();

    // The card mounted closed and opened once; a rerender of the same
    // failure keeps the same element open and does not replay the moment.
    const card = heading.closest<HTMLElement>("[role='status']")!;
    await waitFor(() => expect(card.getAttribute("data-open")).toBe("true"));
    service.seedState({
      session: { ...makeRecoverableSession("committed"), updated_at: "2026-07-11T10:00:00Z" }
    });
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: m.ai_builder_failure_heading_provider_rejected() })
      ).toBe(heading)
    );
    expect(card.getAttribute("data-open")).toBe("true");

    await fireEvent.click(primary);
    expect(resend).toHaveBeenCalledOnce();
  });
});

// ---- fixtures --------------------------------------------------------------

function makePendingOperation(kind: "creating" | "applying"): PendingPlanOperation {
  return { kind, sessionId: "session-1", planId: "plan-1" };
}

function makeApplyResult(): ApplyResult {
  return {
    flow_id: "flow-1",
    flow_name: "Ljud till PDF",
    steps_created: 2,
    steps_updated: 0,
    steps_removed: 0
  };
}

function makeError(code: string): AIBuilderError {
  return {
    schema_version: 2,
    code,
    category: code === "unknown" ? "internal" : "conflict",
    message: "Något gick fel",
    phase: "client",
    request_id: null,
    eneo_error_code: null,
    diagnostic_context: null,
    details: {}
  };
}

/** A step card's trigger reads its number, name, badges and line; match its opening. */
function stepCard(step: number, name: string): RegExp {
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`^${escape(m.ai_builder_step_label({ step }))}\\s*${escape(name)}`);
}

function makeTranscribeStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: "step_a",
    existing_step_ref: null,
    name: "Transkribera ljud",
    assistant_spec: {
      instructions: "Transkribera det uppladdade ljudet.",
      knowledge_refs: [],
      model_ref: null
    },
    input_source: "flow_input",
    input_type: "audio",
    output_mode: "transcribe_only",
    output_type: "text",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    review_policy: { mode: "view" },
    ...overrides
  };
}

function makeRenderStep(overrides: Partial<StepSpec> = {}): StepSpec {
  return {
    plan_step_ref: "step_b",
    existing_step_ref: null,
    name: "Rendera PDF",
    assistant_spec: {
      instructions: "Rendera rapporten till PDF.",
      knowledge_refs: [],
      model_ref: null
    },
    input_source: "previous_step",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "pdf",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  };
}

function makeCreateState() {
  return {
    session: makeSession({
      status: "awaiting_approval",
      target_kind: "create" as const,
      flow_id: null,
      latest_plan_id: "plan-1"
    }),
    currentPlan: makePlan({ status: "proposed" }),
    // A loaded listing with a ready default, as a real session has once the
    // composer can start a turn.
    availableModels: [
      {
        id: "model-1",
        name: "Model",
        provider: "openai",
        availability: { state: "ready" as const }
      }
    ],
    defaultModelId: "model-1",
    modelLoadStatus: "loaded" as const
  };
}

function makeSession(overrides: Partial<AIBuilderSession> = {}): AIBuilderSession {
  return {
    session_id: "session-1",
    status: "chatting",
    target_kind: "edit",
    flow_id: "flow-1",
    latest_plan_id: null,
    conversation: [],
    ...overrides
  };
}

function makeRecoverableSession(
  state: "failed_before_provider" | "provider_outcome_unknown" | "committed"
): AIBuilderSession {
  return makeSession({
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_turn: {
      client_turn_id: "11111111-1111-4111-8111-111111111111",
      state,
      user_message_id: "11111111-1111-4111-8111-111111111112",
      error: null,
      requires_duplicate_provider_spend_acknowledgement: state === "provider_outcome_unknown",
      retry_request: {
        client_turn_id: "11111111-1111-4111-8111-111111111111",
        message: "Bygg ett flöde",
        ui_language: "sv",
        acknowledge_duplicate_provider_spend: false
      }
    }
  });
}

function makePlan(overrides: Partial<ProposedPlan> = {}): ProposedPlan {
  return {
    plan_id: "plan-1",
    status: "proposed",
    proposal: makeProposal(),
    ...overrides
  };
}

function makeProposal(overrides: Partial<ProposedPlan["proposal"]> = {}): ProposedPlan["proposal"] {
  return {
    spec: {
      flow_name: "Ljud till PDF",
      flow_description: "Transkriberar ljud och skriver en PDF-rapport.",
      steps: [makeTranscribeStep(), makeRenderStep()],
      form_fields: []
    },
    assumptions: ["Rapporten skrivs på svenska."],
    lint_warnings: [],
    execution_shape: {
      completion_model_step_count: 1,
      transcription_model_step_count: 1,
      deterministic_step_count: 1,
      schema_constrained_step_count: 0,
      mapped_step_upper_bounds: [
        { plan_step_ref: "step_a", execution_mode: "per_source", maximum_items: 3 }
      ]
    },
    ...overrides
  };
}

export type { AIBuilderTelemetrySummary };

function makeSpace({
  transcriptionModels
}: {
  transcriptionModels: Array<{ can_access?: boolean }>;
}) {
  return {
    id: "space-1",
    name: "Space",
    personal: false,
    organization: false,
    permissions: [],
    members: { items: [], permissions: [] },
    group_members: { items: [], permissions: [] },
    applications: {
      assistants: { items: [], permissions: [] },
      group_chats: { items: [], permissions: [] },
      apps: { items: [], permissions: [] },
      services: { items: [], permissions: [] }
    },
    knowledge: {
      websites: { items: [], permissions: [] },
      groups: { items: [], permissions: [] },
      integration_knowledge_list: { items: [], permissions: [] }
    },
    completion_models: [{ can_access: true }],
    transcription_models: transcriptionModels,
    mcp_servers: []
  } as unknown as Pick<Space, "completion_models" | "transcription_models"> & Partial<Space>;
}
