export class ToolError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
export function publicError(error: unknown): { code: string; message: string } {
  return error instanceof ToolError
    ? { code: error.code, message: error.message }
    : {
        code: "INTERNAL_ERROR",
        message: "Operation failed. Retry or contact the operator with the request ID.",
      };
}
