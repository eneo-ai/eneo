# TypeScript patterns

Prefer types generated from the target deployment's OpenAPI document. When that document is unavailable during development, model only the stable discriminants and request fields the application uses, validate responses at the HTTP boundary, and replace local boundary types when generation becomes possible.

## Closed lifecycle and result types

```ts
type FlowRunStatus =
  | "queued"
  | "running"
  | "awaiting_review"
  | "completed"
  | "failed"
  | "cancelled";

type FlowArtifactAvailability = "available" | "content_purged";

type FlowRunResult =
  | { kind: "inline_text"; text: string }
  | {
      kind: "file_backed_text";
      preview: string;
      file: { file_id: string; availability: FlowArtifactAvailability };
    }
  | { kind: "structured"; value: unknown; output_contract: unknown }
  | {
      kind: "artifact";
      files: Array<{
        file_id: string;
        name: string;
        availability: FlowArtifactAvailability;
      }>;
    }
  | { kind: "outbound_http"; delivery_status: "delivered" };

function renderResult(result: FlowRunResult): string {
  switch (result.kind) {
    case "inline_text":
      return result.text;
    case "file_backed_text":
      return result.file.availability === "available"
        ? `Download complete text from ${result.file.file_id}`
        : "Complete text is no longer available";
    case "structured":
      return JSON.stringify(result.value);
    case "artifact":
      return `${result.files.length} generated file(s)`;
    case "outbound_http":
      return "Delivered";
    default: {
      const unreachable: never = result;
      return unreachable;
    }
  }
}
```

Keep `structured.value` unknown until the published `output_contract` or an application-owned validator accepts it. Do not cast it to an application type without validation.

## Request helper

Keep deployment prefix and authentication outside endpoint methods. Pass a resolved `URL` into the HTTP helper so API-relative bootstrap paths and server-relative `runtime_paths` cannot be confused:

```ts
type Credential =
  { kind: "user"; accessToken: string } | { kind: "service"; apiKey: string };

class FlowApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
    readonly context?: Readonly<Record<string, unknown>>,
    readonly retryAfter?: string,
  ) {
    super(code);
  }
}

async function requestJson<T>(
  url: URL,
  credential: Credential,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (credential.kind === "user")
    headers.set("Authorization", `Bearer ${credential.accessToken}`);
  else headers.set("X-API-Key", credential.apiKey);

  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const fields =
      typeof body === "object" && body !== null
        ? (body as Record<string, unknown>)
        : {};
    const context =
      typeof fields.context === "object" &&
      fields.context !== null &&
      !Array.isArray(fields.context)
        ? (fields.context as Readonly<Record<string, unknown>>)
        : undefined;
    throw new FlowApiError(
      response.status,
      typeof fields.code === "string" ? fields.code : "unknown_flow_error",
      typeof fields.request_id === "string" ? fields.request_id : undefined,
      context,
      response.headers.get("Retry-After") ?? undefined,
    );
  }
  return (await response.json()) as T;
}
```

Resolve bootstrap calls relative to an API base that includes the configured prefix and ends in `/`: `new URL("flows/?space_id=...", apiBase)`. Resolve a published `runtime_paths` value against the deployment origin: `new URL(runtimePath, apiBase.origin)`. Never pass a leading `/flows/...` to `new URL` with a prefixed API base; it would discard that prefix.

For production code, replace the final assertion with the project's boundary validator or generated client. Keep error decoding defensive because platform or proxy failures may not use the Flow envelope. Preserve `context` for recovery hints and `Retry-After` for capacity backoff.

## Create request

```ts
type FlowRunCreateRequest = {
  expected_flow_version: number;
  input_payload_json: Record<string, unknown>;
  step_inputs: Record<string, { file_ids: string[] }>;
};

async function createRun(
  deploymentOrigin: string | URL,
  credential: Credential,
  published: { runtime_paths: { create_run: string } },
  body: FlowRunCreateRequest,
  idempotencyKey: string,
) {
  return requestJson<{ id: string; status: FlowRunStatus }>(
    new URL(published.runtime_paths.create_run, deploymentOrigin),
    credential,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(body),
    },
  );
}
```

Generate the key once when the local submission is created. Store it with the exact serialized intent and reuse it across timeouts and transport retries. A changed form value, version, step binding, or file order is a new logical submission and needs a new key.

## Poll from capabilities

```ts
type StatusCapability = {
  status: string;
  is_active: boolean;
  should_poll: boolean;
  is_terminal: boolean;
  is_cancellable: boolean;
  is_awaiting_review: boolean;
  can_request_redispatch: boolean;
};

function capabilityFor(
  response: { statuses: StatusCapability[] },
  status: string,
): StatusCapability {
  const capability = response.statuses.find((item) => item.status === status);
  return (
    capability ?? {
      status,
      is_active: false,
      should_poll: true,
      is_terminal: false,
      is_cancellable: false,
      is_awaiting_review: false,
      can_request_redispatch: false,
    }
  );
}

const capability = capabilityFor(capabilitiesResponse, summary.status);
if (capability.is_awaiting_review) await loadActiveCheckpoint();
if (!capability.should_poll) await loadAuditedRunDetail();
```

Do not maintain a second status grouping in UI code. Fetch capabilities once per application session or deployment version. The fallback above keeps polling under the application's existing deadline but enables no mutation, which is safer than treating an unknown future status as terminal or cancellable.

## Review compare-and-set

Every review mutation returns a new revision. Use that returned revision for the next operation:

```ts
const edited = await editCheckpoint({
  expected_checkpoint_revision: checkpoint.revision,
  edited_value: correctedValue,
});
const approved = await approveCheckpoint({
  expected_checkpoint_revision: edited.revision,
});
await resumeCheckpoint(
  { expected_checkpoint_revision: approved.revision },
  resumeIdempotencyKey,
);
```

On `flow_review_stale_revision`, refetch instead of retrying the stale body.
