import { type paths as EneoEndpoints } from "./schema";

// In openapi-typescript v7, every operation has a `parameters` property
// where unused locations (path/query/header/cookie) are typed as `never`.
// We only treat the operation as having params if at least one location has
// an actual value type; otherwise the call site can omit `params` entirely.
type EneoParams<
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
> = EneoEndpoints[Endpoint][Method] extends {
  parameters: infer P;
}
  ? Exclude<P[keyof P], undefined> extends never
    ? never
    : P
  : never;

type EneoRequestBody<
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
> = "requestBody" extends keyof EneoEndpoints[Endpoint][Method]
  ? NonNullable<EneoEndpoints[Endpoint][Method]["requestBody"]> extends {
      content: infer Content extends Record<string, unknown>;
    }
    ? Content
    : never
  : never;

type EneoClientRequestBody<
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
> =
  EneoRequestBody<Endpoint, Method> extends { "multipart/form-data": unknown }
    ? Omit<EneoRequestBody<Endpoint, Method>, "multipart/form-data"> & {
        "multipart/form-data": FormData;
      }
    : EneoRequestBody<Endpoint, Method>;

type EneoRequestBodyOption<
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
> =
  EneoRequestBody<Endpoint, Method> extends never
    ? { requestBody?: never }
    : EneoEndpoints[Endpoint][Method] extends { requestBody: unknown }
      ? { requestBody: EneoClientRequestBody<Endpoint, Method> }
      : { requestBody?: EneoClientRequestBody<Endpoint, Method> };

export type JSONRequestBody<
  Method extends "post" | "patch",
  Endpoint extends keyof EneoEndpoints
> = EneoRequestBody<Endpoint, Method>["application/json"];

type Values<T> = T[keyof T];

type Responses<
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
> = EneoEndpoints[Endpoint][Method]["responses"];

type SuccessResponse<Responses extends { [x: number]: any }> = Values<
  Pick<
    Responses,
    Values<{
      [Status in keyof Responses]: Status extends 200 | 201 | 202 | 203 | 204 ? Status : never;
    }>
  >
>["content"]["application/json"];

export type EneoFetchFunction = <
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
>(
  endpoint: Endpoint,
  args: (EneoParams<Endpoint, Method> extends never
    ? { params?: never }
    : { params: EneoParams<Endpoint, Method> }) &
    EneoRequestBodyOption<Endpoint, Method> & {
      method: Method;
      signal?: AbortSignal;
      headers?: Record<string, string>;
    }
) => Promise<SuccessResponse<Responses<Endpoint, Method>>>;

export type EneoBinaryResponse = {
  blob: Blob;
  contentType: string;
  filename?: string;
  headers: Headers;
};

export type EneoBinaryFetchFunction = <
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
>(
  endpoint: Endpoint,
  args: (EneoParams<Endpoint, Method> extends never
    ? { params?: never }
    : { params: EneoParams<Endpoint, Method> }) &
    EneoRequestBodyOption<Endpoint, Method> & {
      method: Method;
      signal?: AbortSignal;
      headers?: Record<string, string>;
    }
) => Promise<EneoBinaryResponse>;

type EneoStreamingEndpoints =
  | "/api/v1/assistants/{id}/sessions/{session_id}/"
  | "/api/v1/assistants/{id}/sessions/"
  | "/api/v1/analysis/assistants/{assistant_id}/"
  | "/api/v1/conversations/"
  | "/api/v1/analysis/conversation-insights/"
  | "/api/v1/flows/ai-builder/sessions/{session_id}/messages";

export type EneoStreamFunction = <Endpoint extends EneoStreamingEndpoints>(
  endpoint: Endpoint,
  args: {
    params: EneoParams<Endpoint, "post">;
    requestBody: EneoClientRequestBody<Endpoint, "post">;
  },
  callbacks: {
    onOpen?: (response: Response) => Promise<void>;
    onClose?: () => void;
    onMessage?: (
      ev: { id: string; event: string; data: string },
      controller: AbortController
    ) => void;
    onError?: (err: any) => number | null | undefined | void;
  },
  abortController?: AbortController | undefined
) => Promise<void>;

export type EneoXhrFunction = <
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
>(
  endpoint: Endpoint,
  args: (EneoParams<Endpoint, Method> extends never
    ? { params?: never }
    : { params: EneoParams<Endpoint, Method> }) &
    EneoRequestBodyOption<Endpoint, Method> & { method: Method },
  callbacks: { onProgress?: (ev: ProgressEvent) => void },
  abortController?: AbortController | undefined
) => Promise<SuccessResponse<Responses<Endpoint, Method>>>;
