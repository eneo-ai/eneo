import type {
  components,
  Flow,
  FlowGraph,
  FlowRun,
  FlowRunContract,
  FlowRunEvidenceExport,
  FlowRunEvidenceWithTypedSteps,
  FlowRunStep,
  FlowRunStepInputs,
  FlowStep,
  FlowTemplateAsset
} from "@intric/intric-js";

type FlowRunCreateRequest = components["schemas"]["FlowRunCreateRequest"];

const isoTimestamp = "2026-03-17T10:05:00Z";
const flowId = "00000000-0000-0000-0000-000000000001";
const stepId = "00000000-0000-0000-0000-000000000101";

const validFlowStep: FlowStep = {
  id: stepId,
  assistant_id: "00000000-0000-0000-0000-000000000201",
  step_order: 1,
  input_source: "flow_input",
  input_type: "document",
  output_mode: "pass_through",
  output_type: "text",
  mcp_policy: "inherit",
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validFlow: Flow = {
  id: flowId,
  tenant_id: "00000000-0000-0000-0000-000000000010",
  space_id: "00000000-0000-0000-0000-000000000020",
  name: "Contract smoke flow",
  description: null,
  steps: [validFlowStep],
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validRunContract: FlowRunContract = {
  flow_id: flowId,
  published_flow_version: 3,
  form_fields: [{ name: "case_id", type: "text", required: true }],
  steps_requiring_input: [
    {
      step_id: stepId,
      step_order: 1,
      required: true,
      input_format: "document",
      accepted_mimetypes: ["application/pdf"]
    }
  ],
  template_readiness: [
    {
      step_id: stepId,
      status: "ready",
      can_edit: true,
      can_download: true,
      template_asset_id: "00000000-0000-0000-0000-000000000601",
      template_file_id: "00000000-0000-0000-0000-000000000602",
      template_name: "decision-template.docx",
      checksum: "sha256:template",
      published_flow_version: 3
    }
  ]
};

const validStepInputs: FlowRunStepInputs = {
  [stepId]: {
    file_ids: ["00000000-0000-0000-0000-000000000701"]
  }
};

const validFlowRun: FlowRun = {
  id: "00000000-0000-0000-0000-000000000301",
  flow_id: flowId,
  flow_version: 3,
  tenant_id: "00000000-0000-0000-0000-000000000010",
  trace_id: "00000000-0000-0000-0000-000000000302",
  status: "completed",
  input_payload_json: { case_id: "CASE-1" },
  output_payload_json: {
    text: "Decision support generated.",
    generated_file_ids: ["00000000-0000-0000-0000-000000000801"]
  },
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validFlowRunStep: FlowRunStep = {
  id: "00000000-0000-0000-0000-000000000501",
  flow_run_id: validFlowRun.id,
  flow_id: flowId,
  tenant_id: validFlowRun.tenant_id,
  step_id: stepId,
  step_order: 1,
  status: "completed",
  input_payload_json: { file_ids: validStepInputs[stepId].file_ids },
  output_payload_json: {
    text: "Step output",
    artifacts: [
      {
        file_id: "00000000-0000-0000-0000-000000000801",
        name: "summary.pdf",
        mimetype: "application/pdf",
        size: 14012
      }
    ]
  },
  created_at: isoTimestamp,
  updated_at: isoTimestamp
};

const validFlowGraph: FlowGraph = {
  nodes: [
    {
      id: stepId,
      label: "Collect source document",
      type: "step",
      step_order: 1
    }
  ],
  edges: []
};

const validFlowEvidenceExport: FlowRunEvidenceExport = {
  schema_version: "flow-evidence-export.v2",
  generated_at: isoTimestamp,
  content_hash: "sha256:evidence",
  manifest: {},
  summary: {},
  redaction: {},
  bundle: {
    run: validFlowRun,
    definition_snapshot: { steps: [validFlowStep] },
    step_results: [validFlowRunStep],
    step_attempts: [],
    debug_export: {
      schema_version: "eneo.flow.debug-export.v2",
      generated_at: isoTimestamp,
      run: {
        run_id: validFlowRun.id,
        flow_id: flowId,
        flow_version: validFlowRun.flow_version,
        status: validFlowRun.status,
        trace_id: validFlowRun.trace_id
      },
      definition: {
        flow_id: flowId,
        version: validFlowRun.flow_version,
        checksum: "sha256:definition",
        steps_count: 1
      },
      definition_snapshot: { steps: [validFlowStep] },
      steps: [],
      security: {
        redaction_applied: false,
        classification_field: "output_classification_override",
        mcp_policy_field: "mcp_policy"
      }
    }
  }
};

const validFlowEvidence: FlowRunEvidenceWithTypedSteps = validFlowEvidenceExport.bundle;

const invalidRunCreateRequest: FlowRunCreateRequest = {
  // @ts-expect-error top-level file_ids is not part of the generated create-run contract.
  file_ids: ["00000000-0000-0000-0000-000000000701"]
};

const invalidFlowStep = {
  ...validFlowStep,
  // @ts-expect-error generated Flow steps reject unknown input sources.
  input_source: "not-a-source"
} satisfies FlowStep;

// @ts-expect-error generated template assets require identifiers, checksum, and status.
const invalidTemplateAsset: FlowTemplateAsset = { name: "decision-template.docx" };

type OutdatedGraphNodeType = "input" | "llm" | "output";

// @ts-expect-error generated graph node type is backend-owned string, not the old frontend union.
const invalidGraphNodeType: OutdatedGraphNodeType = validFlowGraph.nodes[0].type;

const invalidStepInputs: FlowRunStepInputs = {
  // @ts-expect-error frontend run intent requires populated file_ids per step.
  [stepId]: {}
};

void validFlow;
void validRunContract;
void validFlowGraph;
void validFlowEvidence;
void validFlowEvidenceExport;
void invalidRunCreateRequest;
void invalidFlowStep;
void invalidTemplateAsset;
void invalidGraphNodeType;
void invalidStepInputs;
