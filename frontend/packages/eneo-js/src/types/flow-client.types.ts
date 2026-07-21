import { createEneo } from "@eneo/eneo-js";
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

const flows = createEneo({ baseUrl: "https://api.example.test" }).flows;

flows.list({ spaceId: "space-1", limit: 25 });
flows.runContract.get({ id: "flow-1" });
flows.runs.create({
  flow: { id: "flow-1" },
  expected_flow_version: 3,
  idempotencyKey: "flow-run:request-1",
  step_inputs: { "step-1": { file_ids: ["file-1"] } }
});
flows.runs.list({ flowId: "flow-1", status: ["completed", "running"] });

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
