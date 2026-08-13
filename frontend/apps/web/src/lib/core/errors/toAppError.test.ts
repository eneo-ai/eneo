import { EneoError } from "@eneo/eneo-js";
import { describe, expect, test } from "vitest";
import { toAppError } from "./toAppError";

const TRACE_ID = "0af7651916cd43dd8448eb211c80319c";

function backendError(status: number, response?: object, headers?: Headers) {
  return new EneoError(
    "Space not found",
    "RESPONSE",
    status,
    9046,
    response,
    { endpoint: "GET@/api/v1/spaces/" },
    headers
  );
}

describe("toAppError", () => {
  test("carries the backend status, code and trace id", () => {
    const headers = new Headers({ "x-trace-id": TRACE_ID });

    expect(
      toAppError(backendError(404, undefined, headers), { status: 500, message: "boom" })
    ).toEqual({
      status: 404,
      message: "Space not found",
      code: 9046,
      traceId: TRACE_ID
    });
  });

  test("falls back to SvelteKit's status and message for anything else", () => {
    expect(
      toAppError(new TypeError("fetch failed"), { status: 500, message: "Internal Error" })
    ).toEqual({
      status: 500,
      message: "Internal Error",
      code: 0
    });
  });

  test("does not throw while the error it describes is being reported", () => {
    // A load-fetch response refuses header reads it was not told to allow, and
    // a 422 does not guarantee FastAPI's `detail` array.
    const hostileHeaders = {
      get: () => {
        throw new Error('Failed to get response header "x-trace-id"');
      }
    } as unknown as Headers;

    expect(
      toAppError(backendError(422, undefined, hostileHeaders), { status: 500, message: "boom" })
    ).toEqual({
      status: 422,
      message: "A validation error occured.",
      code: 9046,
      traceId: undefined
    });
  });
});
