import { readEventStream } from "@/lib/api/event-stream";
import { queryOptions } from "@tanstack/react-query";
import { API_BASE, apiFetch } from "@/lib/api/base";
import type { EneoClient } from "@/lib/api/browser";
import { apiErrorFromResponse, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type HelperAvailability = Schema<"AvailabilityResponse">;
export type HelperRun = Schema<"HelperRunPublic">;
export type HelperRunResponse = Schema<"HelperRunResponsePublic">;
export type HelperRunStatus = Schema<"HelperRunStatus">;

export const PROMPT_GUIDE_KIND = "prompt_guide" as const;

export function promptGuideAvailabilityQueryOptions(api: EneoClient, targetId: string) {
  return queryOptions({
    queryKey: ["help-assistants", "availability", PROMPT_GUIDE_KIND, targetId],
    queryFn: (): Promise<HelperAvailability> =>
      unwrap(
        api.GET("/api/v1/help-assistants/availability", {
          params: { query: { kind: PROMPT_GUIDE_KIND, target_id: targetId } }
        })
      )
  });
}

export async function startPromptGuideRun({
  targetId,
  question,
  signal,
  onAnswer
}: {
  targetId: string;
  question: string;
  signal?: AbortSignal;
  onAnswer?: (chunk: HelperRunResponse) => void;
}): Promise<HelperRunResponse> {
  return streamHelperRun("/api/v1/help-assistants/runs/", {
    signal,
    body: {
      kind: PROMPT_GUIDE_KIND,
      target_type: "assistant",
      target_id: targetId,
      question,
      stream: true
    },
    onAnswer
  });
}

export async function continuePromptGuideRun({
  runId,
  question,
  signal,
  onAnswer
}: {
  runId: string;
  question: string;
  signal?: AbortSignal;
  onAnswer?: (chunk: HelperRunResponse) => void;
}): Promise<HelperRunResponse> {
  return streamHelperRun(`/api/v1/help-assistants/runs/${encodeURIComponent(runId)}/turns/`, {
    signal,
    body: { question, stream: true },
    onAnswer
  });
}

export async function updateHelperRunStatus(
  runId: string,
  status: Exclude<HelperRunStatus, "in_progress">
): Promise<HelperRun> {
  const url = `${API_BASE}/api/v1/help-assistants/runs/${encodeURIComponent(runId)}/`;
  const response = await apiFetch(url, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status })
  });

  if (!response.ok) {
    throw apiErrorFromResponse(response, await readJsonBody(response));
  }
  return (await readJsonBody(response)) as HelperRun;
}

type StreamBody =
  | {
      kind: typeof PROMPT_GUIDE_KIND;
      target_type: "assistant";
      target_id: string;
      question: string;
      stream: true;
    }
  | { question: string; stream: true };

async function streamHelperRun(
  path: string,
  {
    body,
    signal,
    onAnswer
  }: {
    body: StreamBody;
    signal?: AbortSignal;
    onAnswer?: (chunk: HelperRunResponse) => void;
  }
): Promise<HelperRunResponse> {
  const url = `${API_BASE}${path}`;
  const response = await apiFetch(url, {
    method: "POST",
    headers: {
      accept: "text/event-stream",
      "content-type": "application/json"
    },
    body: JSON.stringify(body),
    signal
  });

  if (!response.ok) {
    throw apiErrorFromResponse(response, await readJsonBody(response));
  }

  if (!response.body) {
    throw new Error("Streaming response had no body.");
  }

  let answer = "";
  const chunks: HelperRunResponse[] = [];
  let streamError: string | null = null;

  await readEventStream(response.body, (data) => {
    if (data === "" || data === "[DONE]") return;

    const chunk = JSON.parse(data) as HelperRunResponse;
    chunks.push(chunk);

    if (chunk.error) {
      streamError = chunk.error;
      return;
    }

    if (chunk.answer) {
      answer += chunk.answer;
      onAnswer?.(chunk);
    }
  });

  if (streamError) throw new Error(streamError);
  const final = chunks.at(-1);
  if (!final) throw new Error("Prompt Guide returned an empty stream.");

  return {
    run: final.run,
    answer,
    references: final.references,
    error: final.error
  };
}

async function readJsonBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text.length > 0 ? text : undefined;
}
