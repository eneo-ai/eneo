import { createEneo } from "@eneo/eneo-js";
import type { AIBuilderBudgetSettingsUpdate } from "./resources";
import type { operations } from "./schema";

type Assert<T extends true> = T;
type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends <Value>() => Value extends Right ? 1 : 2
    ? true
    : false;

type ListFlowsResponse = operations["list_flows"]["responses"][200]["content"]["application/json"];
type GetFlowRunContractResponse =
  operations["get_flow_run_contract"]["responses"][200]["content"]["application/json"];
type CreateFlowRunResponse =
  operations["create_flow_run"]["responses"][201]["content"]["application/json"];

const flows = createEneo({
  apiKey: "synthetic-flow-consumer-key",
  baseUrl: "https://api.example.test"
}).flows;

flows.list({ spaceId: "space-1", limit: 25 });
flows.runContract.get({ id: "flow-1" });
flows.runs.create({
  flow: { id: "flow-1" },
  expected_flow_version: 3,
  idempotencyKey: "flow-run:request-1",
  step_inputs: { "step-1": { file_ids: ["file-1"] } }
});
flows.runs.list({ flowId: "flow-1", status: ["completed", "running"] });
flows.runs.redispatch({
  id: "run-1",
  flowId: "flow-1",
  expected_dispatch_exhausted_at: "2026-07-22T08:30:00Z"
});
flows.runs.cancel({ id: "run-to-cancel", flowId: "flow-1" });

async function compilePublishedFlowWebAppJourney(runtimeFile: File) {
  const flowId = "flow-1";
  const published = await flows.published.get({ id: flowId });
  const contract = await flows.runContract.get({ id: published.id });
  const inputStep = contract.steps_requiring_input?.[0];

  if (!inputStep) return;

  const upload = await flows.steps.runtimeFiles.upload({
    id: flowId,
    stepId: inputStep.step_id,
    file: runtimeFile
  });
  const run = await flows.runs.create({
    flow: { id: flowId },
    expected_flow_version: contract.published_flow_version,
    idempotencyKey: "flow-run:request-1",
    step_inputs: { [inputStep.step_id]: { file_ids: [upload.id] } }
  });
  const statusCapabilities = await flows.runs.statusCapabilities.get();
  const current = await flows.runs.get({ id: run.id, flowId });
  await flows.graph({ id: flowId });
  await flows.graph({ id: flowId, run_id: run.id });
  const status = statusCapabilities.statuses.find((item) => item.status === current.status);

  if (status?.is_awaiting_review) {
    const checkpoint = await flows.runs.reviewCheckpoints.active({ flowId, runId: run.id });
    // Only a checkpoint the flow author opened for editing accepts a new value.
    if (checkpoint && checkpoint.review_mode === "edit") {
      const edited = await flows.runs.reviewCheckpoints.edit({
        flowId,
        runId: run.id,
        checkpointId: checkpoint.id,
        expectedCheckpointRevision: checkpoint.revision,
        editedValue:
          checkpoint.output_type === "json"
            ? ((checkpoint.current_payload_json?.structured as Record<string, unknown>) ?? {})
            : ((checkpoint.current_payload_json?.text as string) ?? "")
      });
      const approved = await flows.runs.reviewCheckpoints.approve({
        flowId,
        runId: run.id,
        checkpointId: edited.id,
        expectedCheckpointRevision: edited.revision
      });
      await flows.runs.reviewCheckpoints.resume({
        flowId,
        runId: run.id,
        checkpointId: approved.id,
        expectedCheckpointRevision: approved.revision,
        idempotencyKey: `flow-review:${approved.id}:${approved.revision}`
      });
    }
  }

  await flows.runs.steps({ flowId, runId: run.id });
  const completed = await flows.runs.get({ id: run.id, flowId });
  switch (completed.result?.kind) {
    case "inline_text":
      completed.result.text;
      break;
    case "file_backed_text":
      completed.result.preview;
      break;
    case "structured":
      completed.result.value;
      completed.result.output_contract;
      break;
    case "artifact":
      completed.result.files;
      break;
    case "outbound_http":
      completed.result.delivery_status;
      break;
  }
  const downloadableFiles =
    completed.result?.kind === "artifact"
      ? completed.result.files
      : completed.result?.kind === "file_backed_text"
        ? [completed.result.file]
        : [];

  for (const file of downloadableFiles) {
    if (file.availability === "available") {
      await flows.runs.artifactSignedUrl({ flowId, runId: run.id, fileId: file.file_id });
    }
  }

  await flows.runs.evidence({ id: run.id, flowId });
  const providerCalls = await flows.runs.providerCalls({ id: run.id, flowId, limit: 50 });
  if (providerCalls.has_more && providerCalls.next_after_event_id) {
    await flows.runs.providerCalls({
      id: run.id,
      flowId,
      limit: 50,
      afterEventId: providerCalls.next_after_event_id
    });
  }
  await flows.runs.exportEvidence({ id: run.id, flowId, format: "json", detail: "redacted" });
}

void compilePublishedFlowWebAppJourney;

// @ts-expect-error list requires a space id.
flows.list({ limit: 25 });
// @ts-expect-error run-contract lookup requires a flow id.
flows.runContract.get({});
// @ts-expect-error generated run statuses reject unknown values.
flows.runs.list({ flowId: "flow-1", status: ["not-a-flow-run-status"] });
// @ts-expect-error top-level file ids are not part of the public run request.
flows.runs.create({ flow: { id: "flow-1" }, file_ids: ["file-1"] });

type _ListFlowsReturn = Assert<Equal<Awaited<ReturnType<typeof flows.list>>, ListFlowsResponse>>;
type _GetFlowRunContractReturn = Assert<
  Equal<Awaited<ReturnType<typeof flows.runContract.get>>, GetFlowRunContractResponse>
>;
type _CreateFlowRunReturn = Assert<
  Equal<Awaited<ReturnType<typeof flows.runs.create>>, CreateFlowRunResponse>
>;
type _AIBuilderUpdateExcludesResponseOnlyHardLimits = Assert<
  Equal<Extract<keyof AIBuilderBudgetSettingsUpdate, `${string}hard_limit`>, never>
>;
