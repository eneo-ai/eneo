import { type paths as IntricEndpoints } from "./schema";

type IntricParams<
  Endpoint extends keyof IntricEndpoints,
  Method extends keyof IntricEndpoints[Endpoint]
> = IntricEndpoints[Endpoint][Method] extends {
  parameters: {
    path?: any;
    query?: any;
  };
}
  ? IntricEndpoints[Endpoint][Method]["parameters"]
  : never;

type IntricRequestBody<
  Endpoint extends keyof IntricEndpoints,
  Method extends keyof IntricEndpoints[Endpoint]
> = IntricEndpoints[Endpoint][Method] extends {
  requestBody: {
    content: any;
  };
}
  ? IntricEndpoints[Endpoint][Method]["requestBody"]["content"]
  : never;

export type JSONRequestBody<
  Method extends "post" | "patch",
  Endpoint extends keyof IntricEndpoints
> = IntricRequestBody<Endpoint, Method>["application/json"];

type Values<T> = T[keyof T];

type Responses<
  Endpoint extends keyof IntricEndpoints,
  Method extends keyof IntricEndpoints[Endpoint]
> = IntricEndpoints[Endpoint][Method]["responses"];

type SuccessResponse<Responses extends { [x: number]: any }> = Values<
  Pick<
    Responses,
    Values<{
      [Status in keyof Responses]: Status extends 200 | 201 | 202 | 203 | 204 ? Status : never;
    }>
  >
>["content"]["application/json"];

type IntricFetchFunction = <
  Endpoint extends keyof IntricEndpoints,
  Method extends keyof IntricEndpoints[Endpoint]
>(
  endpoint: Endpoint,
  args: IntricParams<Endpoint, Method> extends never
    ? IntricRequestBody<Endpoint, Method> extends never
      ? { method: Method; params?: never; requestBody?: never; signal?: AbortSignal }
      : {
          method: Method;
          params?: never;
          requestBody: IntricRequestBody<Endpoint, Method>;
          signal?: AbortSignal;
        }
    : IntricRequestBody<Endpoint, Method> extends never
      ? {
          method: Method;
          params: IntricParams<Endpoint, Method>;
          requestBody?: never;
          signal?: AbortSignal;
        }
      : {
          method: Method;
          params: IntricParams<Endpoint, Method>;
          requestBody: IntricRequestBody<Endpoint, Method>;
          signal?: AbortSignal;
        }
) => Promise<SuccessResponse<Responses<Endpoint, Method>>>;

type IntricStreamingEndpoints =
  | "/api/v1/assistants/{id}/sessions/{session_id}/"
  | "/api/v1/assistants/{id}/sessions/"
  | "/api/v1/analysis/assistants/{assistant_id}/"
  | "/api/v1/conversations/"
  | "/api/v1/analysis/conversation-insights/";

type IntricStreamFunction = <Endpoint extends IntricStreamingEndpoints>(
  endpoint: Endpoint,
  args: {
    params: IntricParams<Endpoint, "post">;
    requestBody: IntricRequestBody<Endpoint, "post">;
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

type IntricXhrFunction = <
  Endpoint extends keyof IntricEndpoints,
  Method extends keyof IntricEndpoints[Endpoint]
>(
  endpoint: Endpoint,
  args: IntricParams<Endpoint, Method> extends never
    ? IntricRequestBody<Endpoint, Method> extends never
      ? { method: Method; params?: never; requestBody?: never }
      : {
          method: Method;
          params?: never;
          requestBody: IntricRequestBody<Endpoint, Method>;
        }
    : IntricRequestBody<Endpoint, Method> extends never
      ? {
          method: Method;
          params: IntricParams<Endpoint, Method>;
          requestBody?: never;
        }
      : {
          method: Method;
          params: IntricParams<Endpoint, Method>;
          requestBody: IntricRequestBody<Endpoint, Method>;
        },
  callbacks: { onProgress?: (ev: ProgressEvent) => void },
  abortController?: AbortController | undefined
) => Promise<SuccessResponse<Responses<Endpoint, Method>>>;
