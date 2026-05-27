import { IntricError, type IntricErrorCode } from "@intric/intric-js";
import type { HandleClientError } from "@sveltejs/kit";

export const handleError: HandleClientError = async ({ error, status, message }) => {
  let code: IntricErrorCode = 0;
  let traceId: string | undefined;
  if (error instanceof IntricError) {
    status = error.status;
    message = error.getReadableMessage();
    code = error.code;
    traceId = error.getTraceId();
    // Surface the backend trace ID so users can pass it to support and it
    // shows up in any client-side error report consuming console output.
    console.error("client error", { status, code, traceId, error });
  } else {
    console.error("client error", error);
  }

  return {
    status,
    message,
    code,
    traceId
  };
};
