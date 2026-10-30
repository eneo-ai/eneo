import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import {
  buildPatches,
  dirtyKeys,
  draftFrom,
  fieldBounds,
  firstProblem,
  rebaseDraft,
  refusalField,
  saveFlowSettings,
  validateDraft,
  type FlowSettingsWriter
} from "./flow-settings";
import { flowSettingsFixture } from "./flow-settings-fixtures";

const settings = flowSettingsFixture();
const baseline = draftFrom(settings);

describe("buildPatches", () => {
  it("sends each endpoint only its changed fields", () => {
    const draft = {
      ...baseline,
      max_files_per_run: 40,
      max_concurrent_runs: 4,
      max_recorded_passage_bytes: 8192,
      max_table_rows: 900,
      allow_run_owner_raw_export_class3: true
    };

    expect(buildPatches(draft, baseline)).toEqual({
      inputLimits: { max_files_per_run: 40 },
      runtime: { max_concurrent_runs: 4 },
      ragEvidence: { max_recorded_passage_bytes: 8192 },
      documentRender: { max_table_rows: 900 },
      evidence: { allow_run_owner_raw_export_class3: true }
    });
    expect(dirtyKeys(draft, baseline)).toHaveLength(5);
  });

  it("sends null for a cleared field and for switching new per-file steps off", () => {
    expect(
      validateDraft({ ...baseline, max_provider_calls_per_mapped_step: null }, baseline, settings)
    ).toEqual({});
    const draft = {
      ...baseline,
      audio_max_duration_seconds: null,
      max_provider_calls_per_mapped_step: null
    };

    expect(buildPatches(draft, baseline)).toEqual({
      inputLimits: { audio_max_duration_seconds: null },
      mapped: { max_provider_calls_per_mapped_step: null }
    });
  });

  it("sends nothing when nothing changed", () => {
    expect(buildPatches(baseline, baseline)).toEqual({});
  });

  it("sends the flow chat's default model, and null to leave chats on the space's own", () => {
    const chosen = { ...baseline, completion_model_id: "model-1" };
    expect(buildPatches(chosen, baseline)).toEqual({
      authoringChat: { completion_model_id: "model-1" }
    });
    expect(validateDraft(chosen, baseline, settings)).toEqual({});

    const saved = draftFrom(
      flowSettingsFixture({ authoringChat: { completion_model_id: "model-1" } })
    );
    expect(buildPatches({ ...saved, completion_model_id: null }, saved)).toEqual({
      authoringChat: { completion_model_id: null }
    });
  });
});

describe("fieldBounds", () => {
  it("shows bytes as kB and the recording length as minutes, within the backend's limits", () => {
    const bounds = fieldBounds(settings);

    expect(bounds.max_recorded_passage_bytes).toEqual({
      min: 1024,
      max: 65_536,
      scale: 1024,
      clearable: true,
      required: false
    });
    expect(bounds.audio_max_duration_seconds).toMatchObject({ min: 60, max: 14_400, scale: 60 });
    expect(bounds.max_step_timeout_seconds.max).toBe(3540);
    expect(bounds.max_concurrent_runs).toMatchObject({ min: 1, max: 8, required: true });
    expect(bounds.max_provider_calls_per_mapped_step).toMatchObject({ min: 2, max: null });
    expect(bounds.max_table_columns.max).toBe(100);
  });
});

describe("validateDraft", () => {
  it("refuses values outside the backend's bounds and a missing run limit", () => {
    const draft = {
      ...baseline,
      max_files_per_run: 1001,
      audio_max_duration_seconds: 30,
      max_concurrent_runs: null,
      max_provider_calls_per_mapped_step: 1,
      max_sources_with_recorded_passages: 2.5
    };

    expect(validateDraft(draft, baseline, settings)).toEqual({
      max_files_per_run: { kind: "range", min: 1, max: 1000 },
      audio_max_duration_seconds: { kind: "range", min: 60, max: 14_400 },
      max_concurrent_runs: { kind: "required" },
      max_provider_calls_per_mapped_step: { kind: "min", min: 2 },
      max_sources_with_recorded_passages: { kind: "integer" }
    });
  });

  it("refuses a normal step timeout longer than the longest", () => {
    const draft = { ...baseline, default_step_timeout_seconds: 1500 };

    expect(validateDraft(draft, baseline, settings)).toEqual({
      default_step_timeout_seconds: { kind: "timeout_order" }
    });
  });

  it("refuses any run limit while the server has no capacity", () => {
    const noCapacity = flowSettingsFixture({
      runtime: { ...settings.runtime, max_concurrent_runs: 0, max_concurrent_runs_capacity: 0 }
    });
    const before = draftFrom(noCapacity);

    expect(validateDraft({ ...before, max_concurrent_runs: 1 }, before, noCapacity)).toEqual({
      max_concurrent_runs: { kind: "no_capacity" }
    });
  });

  it("leaves untouched values alone: the server resolved them", () => {
    const resolvedShort = flowSettingsFixture({
      inputLimits: { ...settings.inputLimits, audio_max_duration_seconds: 30 }
    });
    const before = draftFrom(resolvedShort);

    expect(validateDraft(before, before, resolvedShort)).toEqual({});
  });

  it("names the first problem in the order the page shows the fields", () => {
    expect(
      firstProblem({
        max_object_fields: { kind: "required" },
        max_concurrent_runs: { kind: "required" }
      })
    ).toBe("max_concurrent_runs");
    expect(firstProblem({})).toBeNull();
  });
});

function writer(fail?: keyof FlowSettingsWriter): FlowSettingsWriter & {
  calls: string[];
} {
  const calls: string[] = [];
  const answer =
    <Section extends keyof FlowSettingsWriter>(section: Section) =>
    async (body: unknown) => {
      calls.push(section);
      if (section === fail) throw new Error(`${section} refused`);
      return { ...settings[section], ...(body as object) } as never;
    };
  return {
    calls,
    inputLimits: answer("inputLimits"),
    runtime: answer("runtime"),
    mapped: answer("mapped"),
    ragEvidence: answer("ragEvidence"),
    documentRender: answer("documentRender"),
    evidence: answer("evidence"),
    authoringChat: answer("authoringChat")
  };
}

describe("saveFlowSettings", () => {
  it("writes one endpoint after the other and returns what each answered", async () => {
    const write = writer();
    const outcome = await saveFlowSettings(write, {
      evidence: { allow_space_admin_raw_export_class3: true },
      inputLimits: { max_files_per_run: 12 }
    });

    expect(write.calls).toEqual(["inputLimits", "evidence"]);
    expect(outcome.failure).toBeNull();
    expect(outcome.saved.inputLimits?.max_files_per_run).toBe(12);
    expect(outcome.saved.evidence?.allow_space_admin_raw_export_class3).toBe(true);
  });

  it("stops at the first refusal and keeps what was saved before it", async () => {
    const write = writer("runtime");
    const outcome = await saveFlowSettings(write, {
      inputLimits: { max_files_per_run: 12 },
      runtime: { max_concurrent_runs: 99 },
      mapped: { max_estimated_input_tokens_per_mapped_step: 5000 }
    });

    expect(write.calls).toEqual(["inputLimits", "runtime"]);
    expect(Object.keys(outcome.saved)).toEqual(["inputLimits"]);
    expect(outcome.failure?.section).toBe("runtime");
  });
});

describe("rebaseDraft", () => {
  it("takes the server's values for saved endpoints and keeps the rest of the draft", () => {
    const draft = { ...baseline, max_files_per_run: 12, max_concurrent_runs: 99 };
    const saved = flowSettingsFixture({
      inputLimits: { ...settings.inputLimits, max_files_per_run: 12 }
    });

    const next = rebaseDraft(draft, saved, ["inputLimits"]);

    expect(next.max_files_per_run).toBe(12);
    expect(next.max_concurrent_runs).toBe(99);
    expect(dirtyKeys(next, draftFrom(saved))).toEqual(["max_concurrent_runs"]);
  });
});

describe("refusalField", () => {
  const refusal = (options: ConstructorParameters<typeof EneoApiError>[1]) =>
    new EneoApiError("refused", options);

  it("finds the field a refusal is about by its code, context or validation location", () => {
    expect(
      refusalField(refusal({ status: 400, reason: "max_concurrent_runs_exceeds_server_capacity" }))
    ).toBe("max_concurrent_runs");
    expect(
      refusalField(refusal({ status: 400, reason: "default_timeout_exceeds_tenant_max" }))
    ).toBe("default_step_timeout_seconds");
    expect(
      refusalField(
        refusal({
          status: 400,
          reason: "flow_settings_invalid_payload",
          context: { field: "audio_max_duration_seconds" }
        })
      )
    ).toBe("audio_max_duration_seconds");
    expect(
      refusalField(
        refusal({ status: 422, details: [{ loc: ["body", "max_blocks"], msg: "too large" }] })
      )
    ).toBe("max_blocks");
    expect(
      refusalField(refusal({ status: 400, reason: "flow_authoring_model_without_tools" }))
    ).toBe("completion_model_id");
  });

  it("names no field for other failures", () => {
    expect(refusalField(refusal({ status: 403, reason: "insufficient_tenant_permission" }))).toBe(
      null
    );
    expect(refusalField(new Error("offline"))).toBeNull();
  });
});
