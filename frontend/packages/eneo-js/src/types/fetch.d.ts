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
> = EneoEndpoints[Endpoint][Method] extends {
  requestBody: {
    content: any;
  };
}
  ? EneoEndpoints[Endpoint][Method]["requestBody"]["content"]
  : never;

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

type EneoFetchFunction = <
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
>(
  endpoint: Endpoint,
  args: EneoParams<Endpoint, Method> extends never
    ? EneoRequestBody<Endpoint, Method> extends never
      ? { method: Method; params?: never; requestBody?: never }
      : {
          method: Method;
          params?: never;
          requestBody: EneoRequestBody<Endpoint, Method>;
        }
    : EneoRequestBody<Endpoint, Method> extends never
      ? {
          method: Method;
          params: EneoParams<Endpoint, Method>;
          requestBody?: never;
        }
      : {
          method: Method;
          params: EneoParams<Endpoint, Method>;
          requestBody: EneoRequestBody<Endpoint, Method>;
        }
) => Promise<SuccessResponse<Responses<Endpoint, Method>>>;

type EneoStreamingEndpoints =
  | "/api/v1/assistants/{id}/sessions/{session_id}/"
  | "/api/v1/assistants/{id}/sessions/"
  | "/api/v1/analysis/assistants/{assistant_id}/"
  | "/api/v1/conversations/"
  | "/api/v1/analysis/conversation-insights/";

type EneoStreamFunction = <Endpoint extends EneoStreamingEndpoints>(
  endpoint: Endpoint,
  args: {
    params: EneoParams<Endpoint, "post">;
    requestBody: EneoRequestBody<Endpoint, "post">;
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

type EneoXhrFunction = <
  Endpoint extends keyof EneoEndpoints,
  Method extends keyof EneoEndpoints[Endpoint]
>(
  endpoint: Endpoint,
  args: EneoParams<Endpoint, Method> extends never
    ? EneoRequestBody<Endpoint, Method> extends never
      ? { method: Method; params?: never; requestBody?: never }
      : {
          method: Method;
          params?: never;
          requestBody: EneoRequestBody<Endpoint, Method>;
        }
    : EneoRequestBody<Endpoint, Method> extends never
      ? {
          method: Method;
          params: EneoParams<Endpoint, Method>;
          requestBody?: never;
        }
      : {
          method: Method;
          params: EneoParams<Endpoint, Method>;
          requestBody: EneoRequestBody<Endpoint, Method>;
        },
  callbacks: { onProgress?: (ev: ProgressEvent) => void },
  abortController?: AbortController | undefined
) => Promise<SuccessResponse<Responses<Endpoint, Method>>>;
