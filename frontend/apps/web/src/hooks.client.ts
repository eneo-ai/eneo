import { EneoError, type EneoErrorCode } from "@eneo/eneo-js";
import type { HandleClientError } from "@sveltejs/kit";

export const handleError: HandleClientError = async ({ error, status, message }) => {
  let code: EneoErrorCode = 0;
  if (error instanceof EneoError) {
    status = error.status;
    message = error.getReadableMessage();
    code = error.code;
  } else {
    // On the client we always log the error
    console.error(error);
  }

  return {
    status,
    message,
    code
  };
};
