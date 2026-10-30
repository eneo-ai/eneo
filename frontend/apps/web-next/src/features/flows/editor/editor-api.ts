import { queryOptions, type QueryClient } from "@tanstack/react-query";
import { browserApi } from "@/lib/api/browser";
import { apiErrorFromResponse, EneoApiError, unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import {
  isJsonObject,
  type ClassificationPreview,
  type EditorUpdate,
  type FlowAssistant,
  type FlowPublic,
  type JsonObject,
  type SecurityClassification,
  type TemplateAsset,
  type TemplateInspection,
  type ToolOptions
} from "./step-types";
import type { StepKindPlace } from "./step-kinds";

/**
 * The flow-core endpoints the step editor reads and writes. Every write goes
 * through `PATCH /flows/{id}/editor/`: one revision-fenced edit of the steps
 * and their flow-managed assistants.
 */

/**
 * A refusal from the flow core: the string `code` and its `context` (which
 * often names the step and the field), kept next to the platform error so
 * the editor can show it at the field it is about.
 */
export class FlowEditorError extends EneoApiError {
  readonly context: JsonObject;

  constructor(base: EneoApiError, context: JsonObject) {
    super(base.message, {
      status: base.status,
      code: base.code,
      reason: base.reason,
      traceId: base.traceId,
      errorId: base.errorId,
      details: base.details
    });
    this.name = "FlowEditorError";
    this.context = context;
  }
}

/** Like `unwrap`, but a failure keeps the response's `context`. */
export async function unwrapFlow<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>
): Promise<T> {
  const { data, error, response } = await result;
  if (error !== undefined || !response.ok) {
    const base = apiErrorFromResponse(response, error);
    const context = isJsonObject(error) && isJsonObject(error.context) ? error.context : {};
    throw new FlowEditorError(base, context);
  }
  return data as T;
}

export const flowEditorKeys = {
  /** Every step assistant of the flow: what a new draft revision reads again. */
  assistants: (flowId: string) => ["flows", flowId, "assistants"] as const,
  assistant: (flowId: string, assistantId: string) =>
    [...flowEditorKeys.assistants(flowId), assistantId] as const,
  toolOptions: (flowId: string) => ["flows", flowId, "tool-options"] as const,
  templateFiles: (flowId: string) => ["flows", flowId, "template-files"] as const,
  templateInspection: (flowId: string, assetId: string) =>
    ["flows", flowId, "template-files", assetId, "inspection"] as const,
  classificationPreview: (flowId: string, request: string) =>
    ["flows", flowId, "classification-preview", request] as const,
  insertionKinds: (flowId: string, revision: number, position: number) =>
    ["flows", flowId, "step-kinds", revision, "insertion", position] as const,
  securityClassifications: () => ["security-classifications"] as const,
  executionLimits: () => ["flows", "execution-limits"] as const
};

/**
 * The organisation's step time limit (default and ceiling), as a run applies
 * it. Anyone who may edit flows may read it; if the request fails the editor
 * shows the control without them.
 */
export function executionLimitsQueryOptions() {
  return queryOptions({
    queryKey: flowEditorKeys.executionLimits(),
    queryFn: (): Promise<components["schemas"]["FlowExecutionLimitsPublic"]> =>
      unwrap(browserApi.GET("/api/v1/flows/execution-limits/")),
    retry: false,
    staleTime: 5 * 60_000
  });
}

/**
 * A step assistant, read again when the flow's draft revision moves (the
 * flow page invalidates them all): a save can rewrite its prompt, but time
 * alone does not. Not retried: a refusal would only be repeated.
 */
export function flowAssistantQueryOptions(flowId: string, assistantId: string) {
  return queryOptions({
    queryKey: flowEditorKeys.assistant(flowId, assistantId),
    queryFn: (): Promise<FlowAssistant> =>
      unwrapFlow(
        browserApi.GET("/api/v1/flows/{id}/assistants/{assistant_id}/", {
          params: { path: { id: flowId, assistant_id: assistantId } }
        })
      ),
    retry: false,
    staleTime: Infinity
  });
}

export function toolOptionsQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: flowEditorKeys.toolOptions(flowId),
    queryFn: (): Promise<ToolOptions> =>
      unwrapFlow(
        browserApi.GET("/api/v1/flows/{id}/tool-options", { params: { path: { id: flowId } } })
      )
  });
}

export function templateFilesQueryOptions(flowId: string) {
  return queryOptions({
    queryKey: flowEditorKeys.templateFiles(flowId),
    queryFn: (): Promise<TemplateAsset[]> =>
      unwrapFlow(
        browserApi.GET("/api/v1/flows/{id}/template-files/", { params: { path: { id: flowId } } })
      )
  });
}

export function templateInspectionQueryOptions(flowId: string, assetId: string) {
  return queryOptions({
    queryKey: flowEditorKeys.templateInspection(flowId, assetId),
    queryFn: (): Promise<TemplateInspection> => inspectTemplate(flowId, assetId),
    // A stored template's bytes never change (an upload makes a new asset), and
    // each inspection spawns a process in the tool runtime, so refocusing or
    // choosing the template again reads the cache. Invalidation and eviction
    // still inspect anew; a runtime upgrade shows after a reload.
    staleTime: Infinity
  });
}

export function inspectTemplate(flowId: string, assetId: string): Promise<TemplateInspection> {
  return unwrapFlow(
    browserApi.GET("/api/v1/flows/{id}/template-inspect/", {
      params: { path: { id: flowId }, query: { file_id: assetId } }
    })
  );
}

export function uploadTemplate(flowId: string, file: File): Promise<TemplateAsset> {
  const body = new FormData();
  body.append("upload_file", file);
  return unwrapFlow(
    browserApi.POST("/api/v1/flows/{id}/template-files/", {
      params: { path: { id: flowId } },
      body: body as unknown as { upload_file: string },
      bodySerializer: (formData: unknown) => formData as FormData
    })
  );
}

/**
 * The kinds of step the core allows at one insertion place (1 is first), as
 * the draft save judges them, keyed by the draft revision they judge.
 */
export function insertionKindsQueryOptions(flowId: string, revision: number, position: number) {
  return queryOptions({
    queryKey: flowEditorKeys.insertionKinds(flowId, revision, position),
    queryFn: async (): Promise<StepKindPlace> => {
      const answer = await unwrapFlow(
        browserApi.GET("/api/v1/flows/{id}/step-kinds/", {
          params: { path: { id: flowId }, query: { position } }
        })
      );
      const place = answer.insertions.find((candidate) => candidate.position === position);
      if (!place) throw new Error(`The core answered no insertion place ${position}.`);
      return place;
    }
  });
}

type PreviewRequest = components["schemas"]["FlowSecurityClassificationPreviewRequest"];

export function classificationPreviewQueryOptions(flowId: string, request: PreviewRequest) {
  const key = JSON.stringify(request);
  return queryOptions({
    queryKey: flowEditorKeys.classificationPreview(flowId, key),
    queryFn: (): Promise<ClassificationPreview> =>
      unwrapFlow(
        browserApi.POST("/api/v1/flows/{id}/security-classification/preview", {
          params: { path: { id: flowId } },
          body: request
        })
      ),
    // A refused candidate (a step a save would refuse) has no preview; the
    // editor says so instead of asking again.
    retry: false
  });
}

/** The organisation's classifications; a member without access to them reads levels only. */
export function securityClassificationsQueryOptions() {
  return queryOptions({
    queryKey: flowEditorKeys.securityClassifications(),
    queryFn: async (): Promise<{ items: SecurityClassification[]; enabled: boolean }> => {
      const response = await unwrap(browserApi.GET("/api/v1/security-classifications/"));
      return { items: response.security_classifications, enabled: response.security_enabled };
    },
    retry: false
  });
}

export function getFlow(flowId: string): Promise<FlowPublic> {
  return unwrapFlow(browserApi.GET("/api/v1/flows/{id}/", { params: { path: { id: flowId } } }));
}

export function getFlowAssistant(flowId: string, assistantId: string): Promise<FlowAssistant> {
  return unwrapFlow(
    browserApi.GET("/api/v1/flows/{id}/assistants/{assistant_id}/", {
      params: { path: { id: flowId, assistant_id: assistantId } }
    })
  );
}

/** One editor change: sparse step edits, new steps, the order and the step assistants. */
export function updateFlowEditor(flowId: string, update: EditorUpdate): Promise<FlowPublic> {
  return unwrapFlow(
    browserApi.PATCH("/api/v1/flows/{id}/editor/", {
      params: { path: { id: flowId } },
      body: update
    })
  );
}

type HttpTestRequest = components["schemas"]["HttpTestRequest"];
export type HttpTestResponse = components["schemas"]["HttpTestResponse"];

/**
 * Sends one test request with the step's authored HTTP config. Stored
 * credentials are resolved from the saved step, so the step must be saved.
 */
export function testHttp(flowId: string, request: HttpTestRequest): Promise<HttpTestResponse> {
  return unwrapFlow(
    browserApi.POST("/api/v1/flows/{id}/http-test", {
      params: { path: { id: flowId } },
      body: request
    })
  );
}

/** Puts a freshly read assistant in the cache, so the form shows what was saved. */
export async function refreshFlowAssistant(
  queryClient: QueryClient,
  flowId: string,
  assistantId: string
): Promise<FlowAssistant> {
  const assistant = await getFlowAssistant(flowId, assistantId);
  queryClient.setQueryData(flowEditorKeys.assistant(flowId, assistantId), assistant);
  return assistant;
}
